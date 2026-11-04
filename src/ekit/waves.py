"""Optional wave planning: deliver a product as a sequence of MVPs (waves).

Nothing here does anything unless the project has an approved plan in `.ekit/waves.yaml`.

* A proposal (`docs/planning/waves.proposed.yaml`) may be edited by people and agents.
* `ekit wave approve --by NAME` validates it and writes the approved copy to `.ekit/waves.yaml`.
  The agent's edit tools cannot write `.ekit/*`, and the approving CLI commands are denied to its
  shell tool (see freeze.ALWAYS_BASH), so only a person changes the approved plan.
* Scope is planned per acceptance criterion, qualified by PRD slug: `loan:AC-012`.
  `loan:FEAT-03` is shorthand for every AC of that PRD feature.
* Gates read the approved plan: ACs from later waves cannot be specified yet (`wave.scope`),
  NFRs may be `Deferred (Wn)` until their wave is current, and profiles not active in the
  current wave are skipped and named in every gate report.
"""
from __future__ import annotations

import copy
import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .project import EKIT_DIR, PROJECT_FILE, EkitError, dump_yaml, load_yaml

PROPOSAL = "docs/planning/waves.proposed.yaml"
APPROVED = ".ekit/waves.yaml"

FEAT_HEADING_RE = re.compile(r"^\s*#{2,4}\s+\**(FEAT-\d{2})\b")
AC_DEF_RE = re.compile(r"^\s*[-*|]?\s*\**(AC-\d{3})")
QUALIFIED_RE = re.compile(r"^([a-z0-9][a-z0-9-]*):((?:AC-\d{3})|(?:FEAT-\d{2}))$")
DEFERRED_RE = re.compile(r"^Deferred\s*\(?\s*(W[\w-]+)\s*\)?$", re.IGNORECASE)


# --------------------------------------------------------------------------- PRD index
def parse_prd(text: str) -> dict[str, Any]:
    """Return {"acs": [AC-...], "features": {FEAT-xx: [AC-...]}} from a prd.md.

    ACs are attributed to the closest preceding `### FEAT-xx` heading."""
    acs: list[str] = []
    features: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        m = FEAT_HEADING_RE.match(line)
        if m:
            current = m.group(1)
            features.setdefault(current, [])
            continue
        if line.lstrip().startswith("#"):
            # a non-feature heading (e.g. "## 4. Out of scope") ends the feature section
            if re.match(r"^\s*#{1,2}\s", line):
                current = None
            continue
        m = AC_DEF_RE.match(line)
        if m and m.group(1) not in acs:
            acs.append(m.group(1))
            if current:
                features[current].append(m.group(1))
    return {"acs": acs, "features": features}


def prd_index(root: Path) -> dict[str, dict[str, Any]]:
    req = root / "docs" / "requirements"
    out: dict[str, dict[str, Any]] = {}
    if not req.is_dir():
        return out
    for d in sorted(p for p in req.iterdir() if p.is_dir()):
        prd = d / "prd.md"
        if prd.is_file():
            out[d.name] = parse_prd(prd.read_text(encoding="utf-8"))
    return out


# --------------------------------------------------------------------------- policy
def non_deferrable(kit: Any) -> set[str]:
    try:
        pol = load_yaml(kit.component("waves_policy")) or {}
    except EkitError:
        return set()
    return {str(x) for x in pol.get("non_deferrable") or []}


# --------------------------------------------------------------------------- plan model
@dataclass
class WavePlan:
    data: dict[str, Any]
    index: dict[str, dict[str, Any]]

    @property
    def waves(self) -> list[dict[str, Any]]:
        return list(self.data.get("waves") or [])

    @property
    def ids(self) -> list[str]:
        return [str(w.get("id")) for w in self.waves]

    @property
    def current(self) -> str:
        cur = self.data.get("current")
        return str(cur) if cur else (self.ids[0] if self.ids else "")

    def order(self, wave_id: str) -> int:
        try:
            return self.ids.index(wave_id)
        except ValueError:
            return -1

    def wave(self, wave_id: str) -> dict[str, Any]:
        for w in self.waves:
            if str(w.get("id")) == wave_id:
                return w
        raise EkitError(f"Wave {wave_id} is not in the plan.")

    def expand(self, entry: str) -> list[str]:
        """'loan:FEAT-02' -> ['loan:AC-003', ...]; 'loan:AC-003' -> ['loan:AC-003']. Raises on unknown ids."""
        m = QUALIFIED_RE.match(str(entry).strip())
        if not m:
            raise EkitError(f"scope entry '{entry}' must look like <prd-slug>:AC-001 or <prd-slug>:FEAT-01")
        slug, item = m.group(1), m.group(2)
        prd = self.index.get(slug)
        if prd is None:
            raise EkitError(f"scope entry '{entry}': no PRD docs/requirements/{slug}/prd.md")
        if item.startswith("FEAT-"):
            if item not in prd["features"]:
                raise EkitError(f"scope entry '{entry}': {slug}/prd.md has no {item}")
            return [f"{slug}:{ac}" for ac in prd["features"][item]]
        if item not in prd["acs"]:
            raise EkitError(f"scope entry '{entry}': {slug}/prd.md does not define {item}")
        return [f"{slug}:{item}"]

    def assignment(self) -> dict[str, list[str]]:
        """qualified AC -> wave ids that claim it (validation reports anything but exactly one)."""
        out: dict[str, list[str]] = {}
        for w in self.waves:
            for entry in w.get("scope") or []:
                for ac in self.expand(entry):
                    out.setdefault(ac, []).append(str(w.get("id")))
        return out

    def wave_of(self, qualified_ac: str) -> str | None:
        claims = self.assignment().get(qualified_ac)
        return claims[0] if claims else None

    def acs_of(self, wave_id: str) -> list[str]:
        out: list[str] = []
        for entry in self.wave(wave_id).get("scope") or []:
            for ac in self.expand(entry):
                if ac not in out:
                    out.append(ac)
        return out

    def active_roles(self, all_roles: set[str]) -> set[str]:
        """Roles (backend/frontend) active in the current wave; default: all of them."""
        if not self.current:
            return set(all_roles)
        roles = self.wave(self.current).get("profiles")
        return set(all_roles) if not roles else {str(r) for r in roles} & set(all_roles)

    def deferrals(self) -> dict[str, dict[str, Any]]:
        return {str(d.get("nfr")): d for d in self.data.get("defer") or [] if d.get("nfr")}


# --------------------------------------------------------------------------- loading
def project_mode(root: Path) -> str:
    """'on' (approved plan), 'proposed' (proposal, nothing approved yet), 'off' (declined) or 'undecided'."""
    if (root / APPROVED).is_file():
        return "on"
    if (root / PROPOSAL).is_file():
        return "proposed"
    cfg = load_yaml(root / EKIT_DIR / PROJECT_FILE) if (root / EKIT_DIR / PROJECT_FILE).is_file() else {}
    return "off" if str((cfg or {}).get("waves") or "").lower() == "off" else "undecided"


def load_plan(root: Path, path: str = APPROVED) -> WavePlan | None:
    p = root / path
    if not p.is_file():
        return None
    data = load_yaml(p) or {}
    if not isinstance(data, dict):
        raise EkitError(f"{path} must contain a mapping (apiVersion, kind: WavePlan, waves: [...]).")
    return WavePlan(data=data, index=prd_index(root))


# --------------------------------------------------------------------------- validation
def validate(plan: WavePlan, kit: Any, catalog_ids: set[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    ids = plan.ids
    if not ids:
        return ["the plan has no waves"], warnings
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    errors += [f"wave id {d} is used more than once" for d in dupes]
    if plan.data.get("current") and str(plan.data["current"]) not in ids:
        errors.append(f"current wave {plan.data['current']} is not one of {', '.join(ids)}")

    # scope: every AC of every PRD in exactly one wave, and nothing unknown
    try:
        assign = plan.assignment()
    except EkitError as exc:
        return errors + [str(exc)], warnings
    for ac, claims in sorted(assign.items()):
        if len(claims) > 1:
            errors.append(f"{ac} is planned in more than one wave ({', '.join(claims)})")
    for slug, prd in sorted(plan.index.items()):
        for ac in prd["acs"]:
            if f"{slug}:{ac}" not in assign:
                errors.append(f"{slug}:{ac} is not in any wave (new or changed requirement? place it in a wave)")
    last_with_scope = max((i for i, w in enumerate(plan.waves) if w.get("scope")), default=-1)
    for i, w in enumerate(plan.waves):
        if not w.get("scope"):
            if i > last_with_scope:
                warnings.append(f"wave {w.get('id')} has no scope yet (a placeholder; it cannot become current while empty)")
            else:
                errors.append(f"wave {w.get('id')} has no scope")
        roles = w.get("profiles")
        if roles is not None and (not isinstance(roles, list) or not set(map(str, roles)) <= {"backend", "frontend"}):
            errors.append(f"wave {w.get('id')}: profiles must be a list of backend / frontend")

    # dependencies: prerequisite feature starts in the same or an earlier wave
    for dependent, prereqs in (plan.data.get("dependencies") or {}).items():
        try:
            dep_waves = [plan.order(plan.wave_of(ac) or "") for ac in plan.expand(dependent)]
        except EkitError as exc:
            errors.append(f"dependencies: {exc}")
            continue
        first = min((w for w in dep_waves if w >= 0), default=-1)
        for pre in prereqs or []:
            try:
                pre_waves = [plan.order(plan.wave_of(ac) or "") for ac in plan.expand(pre)]
            except EkitError as exc:
                errors.append(f"dependencies: {exc}")
                continue
            start = min((w for w in pre_waves if w >= 0), default=-1)
            if first >= 0 and start > first:
                errors.append(f"{dependent} starts in {ids[first]} but its prerequisite {pre} only starts in {ids[start]}")

    # deferrals
    blocked = non_deferrable(kit)
    for d in plan.data.get("defer") or []:
        nid, until = str(d.get("nfr") or ""), str(d.get("until") or "")
        where = f"defer {nid or '?'}"
        if nid not in catalog_ids:
            errors.append(f"{where}: not an NFR in the catalogue")
        if nid in blocked:
            errors.append(f"{where}: {nid} is non-deferrable (policy/waves.policy.yaml); it is required from the first wave")
        if until not in ids:
            errors.append(f"{where}: until '{until}' is not a wave of this plan")
        elif plan.order(until) == 0:
            errors.append(f"{where}: until {until} is the first wave, so nothing is deferred")
        for k in ("reason", "approved_by"):
            if not str(d.get(k) or "").strip():
                errors.append(f"{where}: `{k}` is required")
    if "approved_by" in plan.data and not str(plan.data.get("approved_by") or "").strip():
        warnings.append("approved_by is empty")
    return errors, warnings


def catalog_ids(kit: Any) -> set[str]:
    return {n["id"] for n in (kit.nfr_catalog().get("nfrs") or [])}


def require_valid(plan: WavePlan, kit: Any) -> list[str]:
    errors, warnings = validate(plan, kit, catalog_ids(kit))
    if errors:
        raise EkitError("Wave plan is not valid:\n  - " + "\n  - ".join(errors))
    return warnings


# --------------------------------------------------------------------------- feature progress
def feature_progress(root: Path) -> dict[str, dict[str, Any]]:
    """qualified AC -> {"features": [dir names], "green": bool} from trace.yaml + ledgers."""
    out: dict[str, dict[str, Any]] = {}
    specs = root / "specs"
    if not specs.is_dir():
        return out
    for fd in sorted(p for p in specs.iterdir() if p.is_dir()):
        trace = fd / "trace.yaml"
        if not trace.is_file():
            continue
        t = load_yaml(trace) or {}
        slug = Path(str(t.get("prd") or "")).name
        ledger = root / EKIT_DIR / "ledger" / f"{fd.name}.yaml"
        green = False
        if ledger.is_file():
            entries = (load_yaml(ledger) or {}).get("entries") or []
            green = any(e.get("phase") == "green" for e in entries)
        for ac in t.get("acceptance_criteria") or []:
            rec = out.setdefault(f"{slug}:{ac}", {"features": [], "green": False})
            rec["features"].append(fd.name)
            rec["green"] = rec["green"] or green
    return out


# --------------------------------------------------------------------------- commands
def _today() -> str:
    return dt.date.today().isoformat()


def init_proposal(root: Path, force: bool = False) -> Path:
    """Write a proposal skeleton: every AC of every PRD in W1, an empty W2 to move scope into."""
    dest = root / PROPOSAL
    if dest.exists() and not force:
        raise EkitError(f"{PROPOSAL} already exists; edit it, or pass --force to start over.")
    index = prd_index(root)
    if not index:
        raise EkitError("No PRD yet (docs/requirements/<slug>/prd.md). Run /speckit.esdlc.brd first.")
    scope = [f"{slug}:{feat}" for slug, prd in index.items() for feat in prd["features"]]
    loose = [f"{slug}:{ac}" for slug, prd in index.items()
             for ac in prd["acs"] if not any(ac in acs for acs in prd["features"].values())]
    data = {
        "apiVersion": "ekit/v1",
        "kind": "WavePlan",
        "waves": [
            {"id": "W1", "goal": "Face of the system: shell, sign-in and one working happy path per major feature",
             "profiles": ["backend", "frontend"], "scope": scope + loose},
            {"id": "W2", "goal": "Deepen by priority: remaining acceptance criteria, edge cases, deferred NFRs",
             "scope": []},
        ],
        "dependencies": {},
        "defer": [],
    }
    dump_yaml(data, dest)
    _set_project_flag(root, "proposed")
    return dest


def decline(root: Path) -> None:
    if (root / APPROVED).is_file():
        raise EkitError("An approved wave plan exists (.ekit/waves.yaml); delete it in a reviewed change to turn waves off.")
    _set_project_flag(root, "off")


def _set_project_flag(root: Path, value: str) -> None:
    p = root / EKIT_DIR / PROJECT_FILE
    data = (load_yaml(p) or {}) if p.is_file() else {}
    data["waves"] = value
    dump_yaml(data, p)


def approve(root: Path, kit: Any, by: str) -> tuple[WavePlan, list[str]]:
    if not by.strip():
        raise EkitError("--by is required: name the person approving the plan.")
    proposal = load_plan(root, PROPOSAL)
    if proposal is None:
        raise EkitError(f"No proposal at {PROPOSAL}. Run `ekit wave init` (or the planning command) first.")
    previous = load_plan(root, APPROVED)
    data = copy.deepcopy(proposal.data)
    data.pop("approved_by", None)
    history = list((previous.data.get("history") if previous else None) or [])
    data["current"] = previous.current if previous and previous.current in proposal.ids else proposal.ids[0] if proposal.ids else ""
    notes: list[str] = []
    if previous:
        before = previous.deferrals()
        for d in data.get("defer") or []:
            nid = str(d.get("nfr") or "")
            old = before.get(nid)
            if old and proposal.order(str(d.get("until"))) > proposal.order(str(old.get("until"))):
                count = int(old.get("redeferred") or 0) + 1
                d["redeferred"] = count
                notes.append(f"{nid} re-deferred from {old.get('until')} to {d.get('until')} (re-deferral #{count})")
                history.append({"action": "redefer", "nfr": nid, "from": old.get("until"), "to": d.get("until"),
                                "by": by.strip(), "on": _today()})
            elif old and old.get("redeferred"):
                d["redeferred"] = old.get("redeferred")
    # Freeze shorthand: the approved plan lists explicit ACs, so an AC added to a feature later is
    # "not in any wave" until someone places it and approves again (it never slips in silently).
    for w in data.get("waves") or []:
        entries = list(w.get("scope") or [])
        explicit: list[str] = []
        for entry in entries:
            for ac in proposal.expand(entry):
                if ac not in explicit:
                    explicit.append(ac)
        if explicit != entries:
            w["planned_as"] = entries
        w["scope"] = explicit
    if previous:
        try:
            before_acs = set(previous.assignment())
        except EkitError:
            before_acs = set()
        new = [ac for w in data.get("waves") or [] for ac in w["scope"] if ac not in before_acs]
        if new:
            notes.append(f"newly placed: {', '.join(new)}")
    data["approved_by"] = by.strip()
    data["approved_on"] = _today()
    history.append({"action": "approve", "by": by.strip(), "on": _today(), "current": data["current"]})
    data["history"] = history
    plan = WavePlan(data=data, index=proposal.index)
    notes = require_valid(plan, kit) + notes
    dump_yaml(data, root / APPROVED)
    _set_project_flag(root, "on")
    return plan, notes


def advance(root: Path, kit: Any, by: str, carry: bool = False) -> tuple[str, str, list[str]]:
    if not by.strip():
        raise EkitError("--by is required: name the person moving the project to the next wave.")
    plan = load_plan(root)
    if plan is None:
        raise EkitError("No approved wave plan (.ekit/waves.yaml).")
    require_valid(plan, kit)
    cur = plan.current
    i = plan.order(cur)
    if i + 1 >= len(plan.ids):
        raise EkitError(f"{cur} is the last wave in the plan. Add a wave to the proposal and approve it first.")
    nxt = plan.ids[i + 1]
    if not plan.wave(nxt).get("scope") and not carry:
        raise EkitError(f"{nxt} has no scope yet. Plan it in the proposal and approve it before moving there.")
    progress = feature_progress(root)
    open_acs = [ac for ac in plan.acs_of(cur) if not (progress.get(ac) or {}).get("green")]
    notes: list[str] = []
    data = plan.data
    if open_acs:
        if not carry:
            raise EkitError(
                f"{len(open_acs)} acceptance criteria of {cur} have no green feature yet "
                f"({', '.join(open_acs[:8])}{' …' if len(open_acs) > 8 else ''}). Finish them, or pass "
                f"--carry to move them to {nxt} (recorded)."
            )
        for w in data["waves"]:
            wid = str(w.get("id"))
            if wid == cur:
                w["scope"] = [ac for ac in plan.acs_of(cur) if ac not in open_acs]
            elif wid == nxt:
                w["scope"] = list(w.get("scope") or []) + open_acs
        notes.append(f"carried {len(open_acs)} AC(s) from {cur} to {nxt}")
    due = [nid for nid, d in plan.deferrals().items() if str(d.get("until")) == nxt]
    if due:
        notes.append(f"now required in {nxt}: {', '.join(sorted(due))} (no longer deferred)")
    roles_before = WavePlan(data, plan.index).active_roles({"backend", "frontend"})
    data["current"] = nxt
    roles_after = WavePlan(data, plan.index).active_roles({"backend", "frontend"})
    if roles_after - roles_before:
        notes.append(f"newly active: {', '.join(sorted(roles_after - roles_before))}; run `ekit gate baseline` "
                     "(its landing zone and platform NFRs are required from now on)")
    hist = list(data.get("history") or [])
    hist.append({"action": "advance", "from": cur, "to": nxt, "by": by.strip(), "on": _today(),
                 **({"carried": open_acs} if open_acs else {})})
    data["history"] = hist
    require_valid(WavePlan(data, plan.index), kit)
    dump_yaml(data, root / APPROVED)
    # keep the proposal in step, so the next approval starts from what is now true
    if (root / PROPOSAL).is_file():
        prop = load_yaml(root / PROPOSAL) or {}
        prop["waves"] = copy.deepcopy(data["waves"])
        dump_yaml(prop, root / PROPOSAL)
    return cur, nxt, notes


def scope_of_feature(plan: WavePlan, slug: str, feat: str) -> dict[str, list[str]]:
    """{'now': [...], 'earlier': [...], 'later': {'W2': [...]}} for one PRD feature."""
    acs = plan.expand(f"{slug}:{feat}")
    cur = plan.order(plan.current)
    out: dict[str, Any] = {"now": [], "earlier": [], "later": {}}
    for ac in acs:
        w = plan.wave_of(ac)
        o = plan.order(w or "")
        short = ac.split(":", 1)[1]
        if o == cur:
            out["now"].append(short)
        elif 0 <= o < cur:
            out["earlier"].append(short)
        else:
            out["later"].setdefault(w or "unplanned", []).append(short)
    return out
