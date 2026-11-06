"""Design stage (0.7.0): the architecture note and `design.yaml`, the spine of traceability.

* `docs/design/architecture.md`  fixed sections, one to two pages (human)
* `docs/design/design.yaml`      topology, ports, seams, features -> operations/pages, slices, decisions
* `.ekit/design.approved.yaml`   written by `ekit design approve --by` (a person; denied to the agent's shell)

Everything here is deterministic. The `DESIGN-*` checks (gate `design`) and `DESIGN-PORTS-IMPLEMENTED`
(gate `smoke`, an AST scan of the code) read these files; `ekit trace` reads them too.
"""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import re
import shutil
from pathlib import Path
from typing import Any

from . import logbook
from .checks import Finding, GateContext, check
from .project import EkitError, Project, dump_yaml, load_yaml

DESIGN_YAML = "docs/design/design.yaml"
ARCHITECTURE = "docs/design/architecture.md"
APPROVAL = ".ekit/design.approved.yaml"
SEAMS = ("principal", "audit", "request_id", "config", "data_owner")
ADAPTER_KINDS = ("in-process", "separate")     # 0.7.1: `in-process` = one class is both production binding and test double
PACKAGE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SECTIONS = ("topology", "ports", "data model", "interface", "seams", "slices", "decisions")
DECISION_STATUS = ("proposed", "accepted", "rejected", "superseded")
OP_RE = re.compile(r"^[a-z][a-z0-9_]*$")
FEAT_RE = re.compile(r"^FEAT-\d{2}$")
ADR_RE = re.compile(r"^ADR-(\d{4})$")
PAGE_RE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE)\s+/\S*$")
TEMPLATE_DESIGN = "esdlc-design-template.yaml"
TEMPLATE_ARCH = "esdlc-architecture-template.md"


# --------------------------------------------------------------------------- happy-path.md
def parse_happy_path(text: str) -> dict[str, Any]:
    """{'features': {FEAT-01: {'key': bool}}, 'journeys': {J-01: [FEAT-01, ...]}} from happy-path.md."""
    feats: dict[str, dict[str, Any]] = {}
    journeys: dict[str, list[str]] = {}
    cur: tuple[str, str] | None = None
    for line in text.splitlines():
        m = re.match(r"^\s*#{2,4}\s+\**(FEAT-\d{2}|J-\d{2,3})\b", line)
        if m:
            kind = "feat" if m.group(1).startswith("FEAT") else "journey"
            cur = (kind, m.group(1))
            if kind == "feat":
                feats.setdefault(m.group(1), {"key": True})
            else:
                journeys.setdefault(m.group(1), [])
            continue
        if re.match(r"^\s*#{1,2}\s", line):
            cur = None
            continue
        if not cur:
            continue
        k = re.match(r"^\s*[-*]?\s*\**Key\**\s*:\**\s*(yes|no|true|false)\b", line, re.I)
        if k and cur[0] == "feat":
            feats[cur[1]]["key"] = k.group(1).lower() in ("yes", "true")
        f = re.match(r"^\s*[-*]?\s*\**Features\**\s*:\**\s*(.*)$", line, re.I)
        if f and cur[0] == "journey":
            journeys[cur[1]] += re.findall(r"FEAT-\d{2}", f.group(1))
    return {"features": feats, "journeys": journeys}


def happy_paths(root: Path) -> dict[str, dict[str, Any]]:
    req = root / "docs" / "requirements"
    out: dict[str, dict[str, Any]] = {}
    if req.is_dir():
        for d in sorted(p for p in req.iterdir() if p.is_dir()):
            f = d / "happy-path.md"
            if f.is_file():
                out[d.name] = parse_happy_path(f.read_text(encoding="utf-8"))
    return out


def lane(project: Any) -> str:
    return str((getattr(project, "config", None) or {}).get("lane") or "classic")


@check("happy_path.valid")
def happy_path_valid(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """INTAKE-HAPPY-PATH: happy-path lane only (or when the file exists): every key FEAT is in >=1 journey."""
    p = ctx.path(w["file"])
    if not p.is_file():
        if lane(ctx.project) == "happy-path":
            return [Finding("error", f"missing {ctx.project.rel(p)} (happy-path lane: write it from "
                                     "`ekit template esdlc-happy-path-template`)")]
        return []
    hp = parse_happy_path(p.read_text(encoding="utf-8"))
    if not hp["features"]:
        return [Finding("error", f"{ctx.project.rel(p)}: no `### FEAT-xx` sections")]
    in_journey = {f for fs in hp["journeys"].values() for f in fs}
    out = [Finding("error", f"{ctx.project.rel(p)}: key feature {f} appears in no journey")
           for f, v in hp["features"].items() if v["key"] and f not in in_journey]
    out += [Finding("error", f"{ctx.project.rel(p)}: journey {j} names unknown feature {f}")
            for j, fs in hp["journeys"].items() for f in fs if f not in hp["features"]]
    if not hp["journeys"]:
        out.append(Finding("error", f"{ctx.project.rel(p)}: no journeys (`### J-01: ...` with a Features line)"))
    return out


# --------------------------------------------------------------------------- design.yaml
def load_design(root: Path) -> dict[str, Any]:
    p = root / DESIGN_YAML
    if not p.is_file():
        raise EkitError(f"missing {DESIGN_YAML} (run `ekit design init`)")
    data = load_yaml(p)
    if not isinstance(data, dict):
        raise EkitError(f"{DESIGN_YAML} must be a mapping")
    return data


def _design(ctx: GateContext) -> tuple[dict[str, Any] | None, list[Finding]]:
    try:
        return load_design(ctx.project.root), []
    except EkitError as exc:
        return None, [Finding("error", str(exc))]


def key_features(data: dict[str, Any]) -> list[str]:
    return [f for f, v in (data.get("features") or {}).items() if isinstance(v, dict) and v.get("key", True) is not False]


def feature_ops(data: dict[str, Any], feat: str) -> list[str]:
    return [str(o) for o in ((data.get("features") or {}).get(feat) or {}).get("operations") or []]


def feature_pages(data: dict[str, Any], feat: str) -> list[str]:
    return [str(o) for o in ((data.get("features") or {}).get(feat) or {}).get("pages") or []]


def _todo(v: Any) -> bool:
    return isinstance(v, str) and v.strip().upper().startswith("TODO")


@check("design.sections")
def design_sections(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    p = ctx.path(w.get("file", ARCHITECTURE))
    if not p.is_file():
        return [Finding("error", f"missing {ctx.project.rel(p)}")]
    text = p.read_text(encoding="utf-8")
    heads = [re.sub(r"^\d+\.\s*", "", m.group(1)).strip().lower()
             for m in re.finditer(r"^#{1,3}\s+(.+?)\s*$", text, re.M)]
    out = [Finding("error", f"{ctx.project.rel(p)}: no section for '{s}'") for s in SECTIONS
           if not any(s in h for h in heads)]
    out += [Finding("error", f"{ctx.project.rel(p)}:{i}: unresolved placeholder: {ln.strip()[:100]}")
            for i, ln in enumerate(text.splitlines(), 1) if re.search(r"\[TBD|\[NEEDS CLARIFICATION|\bTODO\b", ln)]
    return out


@check("design.schema")
def design_schema(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    data, errs = _design(ctx)
    if data is None:
        return errs
    out: list[Finding] = []
    topo = data.get("topology")
    if not isinstance(topo, str) or not topo.strip() or _todo(topo):
        out.append(Finding("error", "design.yaml: `topology` must be a non-empty string (not TODO)"))
    for key, typ in (("ports", list), ("seams", dict), ("features", dict), ("slices", list), ("decisions", list)):
        if not isinstance(data.get(key), typ) or not data.get(key):
            out.append(Finding("error", f"design.yaml: `{key}` must be a non-empty {'list' if typ is list else 'mapping'}"))
    for f, v in (data.get("features") or {}).items() if isinstance(data.get("features"), dict) else []:
        if not FEAT_RE.match(str(f)) or not isinstance(v, dict):
            out.append(Finding("error", f"design.yaml: feature '{f}' must be FEAT-nn with a mapping"))
            continue
        for lst in ("brs", "operations", "pages"):
            if v.get(lst) is not None and not isinstance(v.get(lst), list):
                out.append(Finding("error", f"design.yaml: {f}.{lst} must be a list"))
        if v.get("package") is not None and (not isinstance(v.get("package"), str) or not PACKAGE_RE.match(v["package"])):
            out.append(Finding("error", f"design.yaml: {f}.package must be a snake_case package name (e.g. vehicles)"))
        for o in v.get("operations") or []:
            if not isinstance(o, str) or not OP_RE.match(o):
                out.append(Finding("error", f"design.yaml: {f}: operation '{o}' must be a snake_case operation_id"))
        for pg in v.get("pages") or []:
            if not isinstance(pg, str) or not PAGE_RE.match(pg):
                out.append(Finding("error", f"design.yaml: {f}: page '{pg}' must look like \"GET /path/{{param}}\""))
    return out


@check("design.ports")
def design_ports(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    data, errs = _design(ctx)
    if data is None:
        return errs
    out, names = [], []
    for i, p in enumerate(data.get("ports") or []):
        if not isinstance(p, dict):
            out.append(Finding("error", f"design.yaml: ports[{i}] must be a mapping"))
            continue
        name = p.get("name")
        names.append(name)
        label = f"port {name or i}"
        if not name or _todo(name):
            out.append(Finding("error", f"design.yaml: ports[{i}] has no name"))
        methods = p.get("methods")
        if not isinstance(methods, list) or not methods or any(_todo(m) or not isinstance(m, str) for m in methods):
            out.append(Finding("error", f"design.yaml: {label} needs at least one declared method"))
        dep = p.get("dependency")
        if not isinstance(dep, str) or not dep.strip() or _todo(dep):
            out.append(Finding("error", f"design.yaml: {label} needs a `dependency` (the FastAPI dependency that provides it)"))
        if p.get("adapter") is not None and p.get("adapter") not in ADAPTER_KINDS:        # 0.7.1
            out.append(Finding("error", f"design.yaml: {label}: `adapter` must be one of {', '.join(ADAPTER_KINDS)}"))
    out += [Finding("error", f"design.yaml: port {n} is declared twice") for n in sorted({n for n in names if names.count(n) > 1})]
    return out


@check("design.seams")
def design_seams(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    data, errs = _design(ctx)
    if data is None:
        return errs
    seams = data.get("seams") if isinstance(data.get("seams"), dict) else {}
    return [Finding("error", f"design.yaml: seam `{s}` is not declared (all five are required: {', '.join(SEAMS)})")
            for s in SEAMS if not isinstance(seams.get(s), dict) or not seams.get(s)]


@check("design.features")
def design_features(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """Every key FEAT has >=1 operation or page and is in exactly one slice; slices are well formed."""
    data, errs = _design(ctx)
    if data is None:
        return errs
    out: list[Finding] = []
    slices = [s for s in data.get("slices") or [] if isinstance(s, dict)]
    ids = [str(s.get("id")) for s in slices]
    out += [Finding("error", f"design.yaml: slice id {i} is used more than once") for i in sorted({i for i in ids if ids.count(i) > 1})]
    where: dict[str, list[str]] = {}
    for s in slices:
        for f in s.get("features") or []:
            where.setdefault(str(f), []).append(str(s.get("id")))
            if f not in (data.get("features") or {}):
                out.append(Finding("error", f"design.yaml: slice {s.get('id')} lists {f}, which is not under `features`"))
    for f in key_features(data):
        if not feature_ops(data, f) and not feature_pages(data, f):
            out.append(Finding("error", f"design.yaml: key feature {f} has no operation or page a user can call"))
        n = len(where.get(f, []))
        if n == 0:
            out.append(Finding("error", f"design.yaml: key feature {f} is in no slice"))
        elif n > 1:
            out.append(Finding("error", f"design.yaml: key feature {f} is in {n} slices ({', '.join(where[f])}); it must be in exactly one"))
    return out


def prd_features(root: Path) -> dict[str, dict[str, Any]]:
    """{slug: {FEAT-xx: {'brs': [...], 'acs': [...]}}} from docs/requirements/*/prd.md (`**Satisfies**:` lines)."""
    from .waves import FEAT_HEADING_RE, parse_prd
    out: dict[str, dict[str, Any]] = {}
    req = root / "docs" / "requirements"
    if not req.is_dir():
        return out
    for d in sorted(p for p in req.iterdir() if p.is_dir()):
        prd = d / "prd.md"
        if not prd.is_file():
            continue
        text = prd.read_text(encoding="utf-8")
        idx = parse_prd(text)
        feats: dict[str, Any] = {f: {"brs": [], "acs": acs} for f, acs in idx["features"].items()}
        cur = None
        for line in text.splitlines():
            m = FEAT_HEADING_RE.match(line)
            if m:
                cur = m.group(1)
                continue
            if cur and re.search(r"Satisfies", line, re.I):
                for b in re.findall(r"BR-\d{3}", line):
                    if b not in feats[cur]["brs"]:
                        feats[cur]["brs"].append(b)
        out[d.name] = feats
    return out


def _in_scope(project: Any, slug: str, feat: str) -> bool:
    plan = getattr(project, "wave_plan", None)
    if plan is None:
        return True
    try:
        from .waves import scope_of_feature
        s = scope_of_feature(plan, slug, feat)
    except EkitError:
        return True
    return bool(s["now"] or s["earlier"]) or not s["later"]


@check("design.brs_listed")
def design_brs_listed(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    data, errs = _design(ctx)
    if data is None:
        return errs
    out: list[Finding] = []
    feats = data.get("features") if isinstance(data.get("features"), dict) else {}
    seen = set()
    for slug, prd in prd_features(ctx.project.root).items():
        for f, v in prd.items():
            if not _in_scope(ctx.project, slug, f):
                continue
            seen.add(f)
            if f not in feats:
                out.append(Finding("error", f"{slug}: {f} is in the PRD but not under `features` in design.yaml"))
                continue
            listed = {str(b) for b in (feats[f] or {}).get("brs") or []}
            out += [Finding("error", f"design.yaml: {f} does not list {b}, which the PRD says it satisfies")
                    for b in v["brs"] if b not in listed]
    return out


def _adr_mentions(files: Any, dec_id: str, title: str) -> bool:
    """0.7.2: the cited ADR's title or body names the decision (its id or its title, case-insensitive, whole words)."""
    pats = [re.compile(rf"(?<!\w){re.escape(t.strip())}(?!\w)", re.I) for t in (dec_id, title) if t.strip()]
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        if any(p.search(text) for p in pats):
            return True
    return False


@check("design.decisions")
def design_decisions(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    data, errs = _design(ctx)
    if data is None:
        return errs
    out: list[Finding] = []
    adr_dir = ctx.path("docs/adr")
    for i, d in enumerate(data.get("decisions") or []):
        if not isinstance(d, dict) or not d.get("id") or not str(d.get("title") or "").strip():
            out.append(Finding("error", f"design.yaml: decisions[{i}] needs `id` and `title`"))
            continue
        if d.get("status") not in DECISION_STATUS:
            out.append(Finding("error", f"design.yaml: decision {d['id']} needs a status ({', '.join(DECISION_STATUS)})"))
        elif d["status"] == "accepted":
            m = ADR_RE.match(str(d.get("adr") or ""))
            if not m:
                out.append(Finding("error", f"design.yaml: accepted decision {d['id']} must cite an ADR (`adr: ADR-0002`)"))
            elif not list(adr_dir.glob(f"{m.group(1)}-*.md")):
                out.append(Finding("error", f"design.yaml: decision {d['id']} cites {d['adr']} but docs/adr/{m.group(1)}-*.md does not exist"))
            elif not _adr_mentions(adr_dir.glob(f"{m.group(1)}-*.md"), str(d["id"]), str(d["title"])):
                out.append(Finding("error", f"design.yaml: decision {d['id']} cites {d['adr']}, but that ADR does not mention {d['id']} "
                                            f"or the decision title \"{d['title']}\"; create the ADR for it with "
                                            f"`ekit adr new \"Title\" --decision {d['id']}` or add the reference to {d['adr']}"))
    return out


@check("design.journeys_declared")
def design_journeys(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    data, errs = _design(ctx)
    if data is None:
        return errs
    hps = happy_paths(ctx.project.root)
    if not hps:
        return [Finding("info", "no happy-path.md; slice journeys were not cross-checked")]
    known = {j for hp in hps.values() for j in hp["journeys"]}
    return [Finding("error", f"design.yaml: slice {s.get('id')} lists journey {j}, which happy-path.md does not define")
            for s in data.get("slices") or [] if isinstance(s, dict) for j in s.get("journeys") or [] if j not in known]


# --------------------------------------------------------------------------- approval (a person)
def fingerprint(root: Path) -> dict[str, str]:
    def sha(rel: str) -> str:
        p = root / rel
        return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() if p.is_file() else ""
    return {"design_yaml": sha(DESIGN_YAML), "architecture_md": sha(ARCHITECTURE)}


def approval(root: Path) -> dict[str, Any] | None:
    p = root / APPROVAL
    return (load_yaml(p) or {}) if p.is_file() else None


@check("design.approved")
def design_approved(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    rec = approval(ctx.project.root)
    if not rec:
        return [Finding("error", "the design is not approved: a person reviews it and runs `ekit design approve --by \"Name\"`")]
    if rec.get("fingerprint") != fingerprint(ctx.project.root):
        return [Finding("error", f"the design changed after it was approved by {rec.get('by')} on {rec.get('on')}: "
                                 "review the change and run `ekit design approve --by \"Name\"` again")]
    return [Finding("info", f"approved by {rec.get('by')} on {rec.get('on')}")]


def approve(project: Project, by: str) -> list[str]:
    if not by.strip():
        raise EkitError("--by is required: name the person approving the design.")
    from . import gates
    res, _ = gates.run_gate(project, "design")
    bad = [c for c in res.checks if c.id != "DESIGN-APPROVED" and c.status == "fail"]
    if bad:
        raise EkitError("The design is not valid yet; fix these first (`ekit gate design`):\n  - " + "\n  - ".join(
            f"{c.id}: {(f.message.splitlines() or [''])[0]}" for c in bad for f in c.findings if f.level == "error")[:1500])
    root = project.root
    rec = {"apiVersion": "ekit/v1", "kind": "DesignApproval", "by": by.strip(), "on": dt.date.today().isoformat(),
           "fingerprint": fingerprint(root)}
    dump_yaml(rec, root / APPROVAL)
    logbook.append(root, {"kind": "state.design.approve", "feature": None, "reason": f"design approved by {by.strip()}",
                          "by": by.strip(), "via": logbook.via(), "actor": logbook.actor(root)})
    from . import waves
    notes = [f"design approved by {by.strip()}; commit {APPROVAL}"]
    notes += waves.place_from_design(root, load_design(root), by)      # 0.7.1: W0 scope comes from the slices
    return notes


# --------------------------------------------------------------------------- init
def init(project: Project, *, from_code: bool = False, force: bool = False) -> list[str]:
    root = project.root
    ext = project.kit.component("extension") / "templates"
    notes: list[str] = []
    dest_y, dest_a = root / DESIGN_YAML, root / ARCHITECTURE
    if (dest_y.exists() or dest_a.exists()) and not force:
        raise EkitError(f"{DESIGN_YAML} or {ARCHITECTURE} already exists; edit it, or pass --force to start over.")
    dest_y.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ext / TEMPLATE_ARCH, dest_a)
    if from_code:
        dump_yaml(draft_from_code(project), dest_y)
        notes.append("drafted from code: ports from `Protocol` classes, features from the PRD, operations from "
                     "reports/openapi.json when present. A person completes the TODOs (topology, decisions, "
                     "operation to feature mapping) before the gate can pass")
    else:
        shutil.copyfile(ext / TEMPLATE_DESIGN, dest_y)
    notes.insert(0, f"wrote {ARCHITECTURE} and {DESIGN_YAML}; fill them, then `ekit gate design`")
    return notes


def source_roots(project: Any) -> list[Path]:
    roots = []
    for prof in getattr(project, "profiles", []) or []:
        src = ((prof.data.get("layout") or {}).get("source")) or "src"
        roots.append(prof.root / src)
    roots.append(project.root / "src")
    seen, out = set(), []
    for r in roots:
        if r.is_dir() and r.resolve() not in seen:
            seen.add(r.resolve())
            out.append(r)
    return out


def scan_classes(project: Any) -> dict[str, list[dict[str, Any]]]:
    """class name -> [{'file', 'protocol': bool, 'methods': set}] and top-level function names under `__functions__`."""
    out: dict[str, list[dict[str, Any]]] = {}
    funcs: list[dict[str, Any]] = []
    for r in source_roots(project):
        for f in sorted(r.rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            rel = project.rel(f)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    bases = {b.attr if isinstance(b, ast.Attribute) else b.id for b in node.bases
                             if isinstance(b, (ast.Name, ast.Attribute))}
                    methods = {n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
                    out.setdefault(node.name, []).append({"file": rel, "protocol": "Protocol" in bases, "methods": methods})
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    used = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
                        n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
                    funcs.append({"name": node.name, "file": rel, "uses": used})
    out["__functions__"] = funcs
    return out


def draft_from_code(project: Project) -> dict[str, Any]:
    import json
    classes = scan_classes(project)
    ports = [{"name": n, "methods": sorted(m for m in infos[0]["methods"] if not m.startswith("_")) or ["TODO"],
              "dependency": "TODO"}
             for n, infos in sorted(classes.items()) if n != "__functions__" and any(i["protocol"] for i in infos)]
    feats: dict[str, Any] = {}
    for _slug, prd in prd_features(project.root).items():
        for f, v in prd.items():
            feats[f] = {"key": True, "brs": list(v["brs"]), "operations": ["TODO"], "pages": []}
    data: dict[str, Any] = {
        "topology": "TODO",
        "ports": ports or [{"name": "TODO", "methods": ["TODO"], "dependency": "TODO"}],
        "seams": {"principal": {"impl": "TODO"}, "audit": {"impl": "TODO"}, "request_id": {"impl": "TODO"},
                  "config": {"impl": "TODO"}, "data_owner": {"field": "TODO"}},
        "features": feats or {"FEAT-01": {"key": True, "brs": [], "operations": ["TODO"], "pages": []}},
        "slices": [{"id": "S0", "features": sorted(feats) or ["FEAT-01"], "journeys": []}],
        "decisions": [{"id": "D1", "title": "Topology", "status": "proposed", "adr": None}],
    }
    spec = project.root / "reports" / "openapi.json"
    if spec.is_file():
        try:
            from .smoke import operations_of
            data["unassigned_operations"] = sorted(operations_of(json.loads(spec.read_text(encoding="utf-8"))))
        except (ValueError, EkitError):
            pass
    return data


# --------------------------------------------------------------------------- DESIGN-PORTS-IMPLEMENTED
@check("design.ports_implemented")
def ports_implemented(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    """AST scan: each port is a Protocol class with every declared method, its dependency function exists,
    and at least one other class implements all methods (adapter); a fake (`InMemory*`/`Fake*`) is a warning."""
    try:
        data = load_design(ctx.project.root)
    except EkitError:
        return [Finding("info", "no design.yaml; ports were not scanned")]
    classes = scan_classes(ctx.project)
    funcs = {f["name"] for f in classes.get("__functions__", [])}
    uses: dict[str, set[str]] = {}
    for f in classes.get("__functions__", []):
        uses.setdefault(f["name"], set()).update(f.get("uses") or set())
    out: list[Finding] = []
    for p in data.get("ports") or []:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        name, methods = str(p["name"]), {str(m) for m in p.get("methods") or []}
        infos = classes.get(name) or []
        proto = next((i for i in infos if i["protocol"]), None)
        if proto is None:
            out.append(Finding("error", f"port {name}: no `class {name}(Protocol)` found in the source"))
            continue
        lacking = sorted(methods - proto["methods"])
        if lacking:
            out.append(Finding("error", f"port {name} ({proto['file']}) lacks declared method(s): {', '.join(lacking)}"))
        dep = p.get("dependency")
        if dep and str(dep) not in funcs:
            out.append(Finding("error", f"port {name}: dependency function `{dep}` is not defined in the source"))
        impls = [(n, i) for n, ii in classes.items() if n != "__functions__" and n != name
                 for i in ii if not i["protocol"] and methods <= i["methods"]]
        adapters = [n for n, _ in impls if not re.match(r"(InMemory|Fake)", n)]
        # 0.7.1: `adapter: in-process` (or one class the dependency function itself binds) is a single class
        # that is both the production binding and the test double.
        bound = [n for n, _ in impls if n in uses.get(str(dep), set())] if dep else []
        if not adapters and impls and (p.get("adapter") == "in-process" or bound):
            pass
        elif not adapters:
            hint = ("; if one in-process class is the production binding, declare `adapter: in-process` on the port "
                    "in design.yaml" if impls else "")
            out.append(Finding("error", f"port {name}: no adapter class implements {', '.join(sorted(methods))}{hint}"))
        if not any(re.match(r"(InMemory|Fake)", n) for n, _ in impls) and p.get("adapter") != "in-process":
            out.append(Finding("warn", f"port {name}: no in-memory fake (a class named InMemory*/Fake*) for unit tests"))
    return out
