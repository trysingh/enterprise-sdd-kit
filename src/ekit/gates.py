"""Gate engine: load policy (+ project overrides), resolve placeholders, run checks, report."""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from .checks import REGISTRY, Finding, GateContext
from .kitsource import cli_pin
from .project import EkitError, Project, load_yaml

OVERRIDES_FILE = ".ekit/policy.overrides.yaml"


@dataclass
class CheckResult:
    id: str
    type: str
    severity: str
    findings: list[Finding] = field(default_factory=list)
    skipped: str | None = None

    @property
    def status(self) -> str:
        if self.skipped:
            return "skipped"
        levels = {f.level for f in self.findings}
        if "error" in levels:
            return "fail" if self.severity == "error" else "warn"
        if "warn" in levels:
            return "warn"
        return "pass"


@dataclass
class GateResult:
    gate: str
    description: str
    context: dict[str, str]
    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(c.status != "fail" for c in self.checks)


def load_policy(project: Project) -> dict[str, Any]:
    policy = project.kit.policy()
    if (policy or {}).get("kind") != "GatePolicy":
        raise EkitError("Kit policy file is not a GatePolicy.")
    return policy


def load_overrides(project: Project) -> tuple[dict[str, Any], list[str]]:
    """Valid overrides need a non-empty `reason`, a named approver (`approved_by`) and an
    `expires` date that has not passed. Anything else is ignored and reported, so a relaxation
    is always explained, owned and time-boxed, and turns back into a failure by itself."""
    p = project.root / OVERRIDES_FILE
    if not p.is_file():
        return {}, []
    data = load_yaml(p) or {}
    notes, valid = [], {}
    today = dt.date.today()
    for cid, ov in (data.get("overrides") or {}).items():
        if not isinstance(ov, dict):
            notes.append(f"override for {cid} ignored: it must be a mapping with reason, approved_by and expires")
            continue
        missing = [k for k in ("reason", "approved_by", "expires") if not str(ov.get(k) or "").strip()]
        if missing:
            notes.append(f"override for {cid} ignored: {', '.join('`' + k + '`' for k in missing)} required")
            continue
        exp = ov.get("expires")
        try:
            exp_d = exp if isinstance(exp, dt.date) else dt.date.fromisoformat(str(exp))
        except ValueError:
            notes.append(f"override for {cid}: bad expires date '{exp}'; ignored")
            continue
        if exp_d < today:
            notes.append(f"override for {cid} expired on {exp_d}; ignored")
            continue
        valid[cid] = ov
    return valid, notes


def wave_notes(project: Project) -> list[str]:
    """With an approved wave plan, every report says which wave is current and what it skips."""
    plan = getattr(project, "wave_plan", None)
    if plan is None:
        return []
    from .waves import catalog_ids, validate
    notes = [f"waves: current {plan.current} of {', '.join(plan.ids)} (.ekit/waves.yaml, approved by "
             f"{plan.data.get('approved_by') or '?'} on {plan.data.get('approved_on') or '?'})"]
    inactive = project.inactive_profiles
    if inactive:
        notes.append(f"not active in {plan.current}: {', '.join(p.id for p in inactive)}. Their commands, paths, "
                     "environment and BDD runs are skipped, and NFRs that apply only to them are not required yet")
    errors, _ = validate(plan, project.kit, catalog_ids(project.kit))
    if errors:
        notes.append(f"the approved wave plan is no longer valid ({len(errors)} problem(s), e.g. {errors[0]}); "
                     "run `ekit wave validate`")
    return notes


def _subst(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return re.sub(r"\{(feature_dir|prd_dir)\}", lambda m: mapping.get(m.group(1), m.group(0)), value)
    if isinstance(value, list):
        return [_subst(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: _subst(v, mapping) for k, v in value.items()}
    return value


def gate_ids(project: Project) -> list[str]:
    return [g["id"] for g in load_policy(project)["spec"]["gates"]]


def run_gate(
    project: Project, gate_id: str, *, feature: str | None = None, prd: str | None = None
) -> tuple[GateResult, list[str]]:
    policy = load_policy(project)
    defaults = policy["spec"].get("defaults") or {}
    gate = next((g for g in policy["spec"]["gates"] if g["id"] == gate_id), None)
    if gate is None:
        raise EkitError(f"Unknown gate '{gate_id}'. Known: {', '.join(gate_ids(project))}")
    overrides, notes = load_overrides(project)
    pin = cli_pin(project.root)
    if not pin.matches:
        notes.insert(0, pin.message())
    notes += wave_notes(project)

    ctx = GateContext(project=project)
    kind = gate.get("context", "project")
    if kind == "feature":
        ctx.feature_dir = project.resolve_feature(feature)
        try:
            ctx.prd_dir = project.resolve_prd(prd, ctx.feature_dir)
        except EkitError:
            ctx.prd_dir = None
    elif kind == "prd":
        if feature:
            ctx.feature_dir = project.resolve_feature(feature)
        ctx.prd_dir = project.resolve_prd(prd, ctx.feature_dir)

    mapping = {}
    if ctx.feature_dir:
        mapping["feature_dir"] = project.rel(ctx.feature_dir)
    if ctx.prd_dir:
        mapping["prd_dir"] = project.rel(ctx.prd_dir)

    results: list[CheckResult] = []
    for chk in gate.get("checks", []):
        cid, ctype = chk["id"], chk["type"]
        severity = chk.get("severity", defaults.get("severity", "error"))
        ov = overrides.get(cid, {})
        if "severity" in ov:
            severity = ov["severity"]
        cr = CheckResult(id=cid, type=ctype, severity=severity)
        if ov.get("enabled") is False:
            cr.skipped = f"disabled by override: {ov['reason']}"
            results.append(cr)
            continue
        fn = REGISTRY.get(ctype)
        if fn is None:
            cr.findings = [Finding("error", f"unknown check type '{ctype}' (kit/ekit version mismatch?)")]
            results.append(cr)
            continue
        params = _subst(chk.get("with") or {}, mapping)
        unresolved = re.findall(r"\{(feature_dir|prd_dir)\}", json.dumps(params))
        if unresolved:
            cr.findings = [Finding("error", f"cannot resolve {{{unresolved[0]}}}; pass --feature/--prd")]
            results.append(cr)
            continue
        try:
            cr.findings = fn(ctx, params)
        except EkitError as exc:
            cr.findings = [Finding("error", str(exc))]
        results.append(cr)

    return GateResult(gate_id, gate.get("description", ""), mapping, results), notes


# ---------------------------------------------------------------------------- reporting
SYMBOL = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skipped": "SKIP"}


def render_text(res: GateResult, notes: list[str], verbose: bool = False) -> str:
    lines = [f"Gate '{res.gate}': {res.description}"]
    for k, v in res.context.items():
        lines.append(f"  {k}: {v}")
    for n in notes:
        lines.append(f"  note: {n}")
    for c in res.checks:
        lines.append(f"  [{SYMBOL[c.status]}] {c.id} ({c.type})" + (f" — {c.skipped}" if c.skipped else ""))
        for f in c.findings:
            if f.level == "info" and not verbose:
                continue
            tag = {"error": "x" if c.severity == "error" else "!", "warn": "!", "info": "i"}[f.level]
            first, *rest = f.message.splitlines() or [""]
            lines.append(f"      {tag} {first}")
            lines.extend(f"          {r}" for r in rest)
    lines.append(f"Result: {'PASSED' if res.passed else 'FAILED'}")
    return "\n".join(lines)


def render_json(res: GateResult, notes: list[str]) -> str:
    return json.dumps({
        "gate": res.gate,
        "passed": res.passed,
        "context": res.context,
        "notes": notes,
        "checks": [
            {"id": c.id, "type": c.type, "severity": c.severity, "status": c.status,
             "skipped": c.skipped, "findings": [f.__dict__ for f in c.findings]}
            for c in res.checks
        ],
    }, indent=2)


def render_junit(res: GateResult, notes: list[str] | None = None) -> str:
    fails = sum(1 for c in res.checks if c.status == "fail")
    skips = sum(1 for c in res.checks if c.status == "skipped")
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<testsuite name={quoteattr("ekit.gate." + res.gate)} tests="{len(res.checks)}" failures="{fails}" skipped="{skips}">']
    if notes:   # e.g. a CLI that differs from the project pin, ignored overrides: CI must see these too
        out.append(f'  <system-out>{escape(chr(10).join("note: " + n for n in notes))}</system-out>')
    for c in res.checks:
        out.append(f'  <testcase classname={quoteattr("ekit.gate." + res.gate)} name={quoteattr(c.id)}>')
        msg = "\n".join(f"{f.level}: {f.message}" for f in c.findings if f.level != "info")
        if c.status == "fail":
            out.append(f'    <failure message={quoteattr(c.type)}>{escape(msg)}</failure>')
        elif c.status == "skipped":
            out.append(f'    <skipped message={quoteattr(c.skipped or "")}/>')
        elif msg:
            out.append(f'    <system-out>{escape(msg)}</system-out>')
        out.append('  </testcase>')
    out.append('</testsuite>')
    return "\n".join(out)


def write_report(res: GateResult, notes: list[str], fmt: str, out: Path | None, verbose: bool) -> str:
    text = {"text": lambda: render_text(res, notes, verbose),
            "json": lambda: render_json(res, notes),
            "junit": lambda: render_junit(res, notes)}[fmt]()
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return text
