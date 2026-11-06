"""Change requests (ekit 0.5.0): bug fixes and features taken straight from the prompt.

Brownfield work rarely arrives as a BRD. It arrives as a sentence: "the unread badge doesn't clear
after I open a chat", "add a 'mark all read' button". Until 0.5.0 such a request either went through
`/speckit.esdlc.brd` (a file, a PRD, the whole intake) or through `/speckit.specify` untraced. Now:

* `ekit change new` turns the request text into a **change-request folder**
  `docs/requirements/cr-NNNN-<slug>/` with the request kept verbatim (`request.md`) and its metadata
  (`change.yaml`: type, affected features, bug facts, scenarios it supersedes). The folder is a small
  PRD folder (`brd.md`, `prd.md`, `open-questions.yaml` are written by `/speckit.esdlc.change`), so every
  existing gate (intake, ready, spec, scenarios, plan, red, green) works on it unchanged.
* `ekit change candidates "<text>"` ranks the existing features a request probably touches, so the
  model reads two specs, not twenty.
* `ekit change retire` (a person) retires an existing frozen scenario that a change supersedes: the
  scenario is removed from its feature file, the rest must be byte-identical, and the feature's ledger
  gets a `rebase` entry with the new fingerprints. Without it, a behaviour change to a delivered feature
  could never go green (the old frozen scenario keeps asserting the old behaviour).

The red/green cycle is the same for every change. What differs is what "red" proves:

* `bug`: the new scenario reproduces the defect against the **committed, unmodified** production code
  and fails on an assertion (`RED-BUG-REPRODUCED`). No stubs: a 501 would prove nothing about the bug.
* `enhancement` / `feature`: as for any feature; new routes are stubbed with 501 (golden projects:
  in the affected feature's package for an enhancement).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import logbook
from .project import EkitError, dump_yaml, git, load_yaml

TYPES = ("bug", "enhancement", "feature")
CR_DIR_RE = re.compile(r"^cr-(\d{4})-[a-z0-9][a-z0-9-]*$")
CR_ID_RE = re.compile(r"^(?:CR-?|cr-?)?(\d{1,4})$")
SCN_RE = re.compile(r"^SCN-\d{3}-\d{2}$")
REQUEST_MARKER = "## Request (verbatim)"
PLACEHOLDER = "[PASTE THE USER'S REQUEST HERE, VERBATIM]"
REQ_DIR = Path("docs") / "requirements"


def _now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def _who(root: Path) -> str:
    from .freeze import _who as who
    return who(root)


def slugify(title: str) -> str:
    words = re.sub(r"[^a-z0-9]+", " ", title.lower()).split()
    return "-".join(words[:6])[:48].strip("-") or "change"


def cr_id(num: int | str) -> str:
    return f"CR-{int(num):04d}"


# --------------------------------------------------------------------------- lookup
def all_dirs(root: Path) -> list[Path]:
    req = root / REQ_DIR
    if not req.is_dir():
        return []
    return sorted(p for p in req.iterdir() if p.is_dir() and CR_DIR_RE.match(p.name))


def is_change_dir(path: Path | None) -> bool:
    return bool(path and (path / "change.yaml").is_file())


def find(root: Path, ref: str) -> Path:
    """`CR-0007`, `cr-0007`, `7`, `0007`, a folder name or a path -> the change folder."""
    ref = (ref or "").strip().strip("\"'")
    if not ref:
        raise EkitError("Name a change request: CR-0007")
    p = Path(ref)
    for cand in (p if p.is_absolute() else root / p, root / REQ_DIR / ref):
        if cand.is_dir() and is_change_dir(cand):
            return cand.resolve()
    m = CR_ID_RE.match(ref) or re.match(r"^cr-(\d{4})-", ref)
    if m:
        num = int(m.group(1))
        hits = [d for d in all_dirs(root) if int(CR_DIR_RE.match(d.name).group(1)) == num]
        if len(hits) == 1:
            return hits[0].resolve()
    known = ", ".join(f"{cr_id(CR_DIR_RE.match(d.name).group(1))} ({d.name})" for d in all_dirs(root)) or "none yet"
    raise EkitError(f"No change request '{ref}'. Known: {known}")


def load(cr_dir: Path) -> dict[str, Any]:
    data = load_yaml(cr_dir / "change.yaml") if (cr_dir / "change.yaml").is_file() else None
    if not isinstance(data, dict):
        raise EkitError(f"{cr_dir.name}: change.yaml missing or not a mapping")
    return data


def for_feature(root: Path, feature_dir: Path | None) -> tuple[Path, dict[str, Any]] | None:
    """The change request a Spec Kit feature folder implements (via its trace.yaml `prd:`), or None."""
    if not feature_dir:
        return None
    trace_p = feature_dir / "trace.yaml"
    if not trace_p.is_file():
        return None
    prd = (load_yaml(trace_p) or {}).get("prd")
    if not prd:
        return None
    d = (root / prd).resolve()
    if not is_change_dir(d):
        return None
    try:
        return d, load(d)
    except EkitError:
        return None


def features_of(root: Path, cr_dir: Path) -> list[str]:
    """Spec folders whose trace.yaml points at this change."""
    out = []
    specs = root / "specs"
    if not specs.is_dir():
        return out
    for d in sorted(specs.iterdir()):
        t = d / "trace.yaml"
        if t.is_file():
            prd = (load_yaml(t) or {}).get("prd")
            if prd and (root / prd).resolve() == cr_dir.resolve():
                out.append(d.name)
    return out


def affected_features(data: dict[str, Any]) -> list[str]:
    aff = data.get("affects") or {}
    feats = aff.get("features") if isinstance(aff, dict) else aff
    return [str(f) for f in (feats or [])]


# --------------------------------------------------------------------------- new
REQUEST_TEMPLATE = """# {cid}: {title}

**Type**: {type} | **Ticket**: {ticket} | **Recorded**: {at} by {by}

This file keeps the request exactly as it was given. It is the source every `BR-` row in
`brd.md` quotes. Do not edit it after intake; a changed request is a new change request.

{marker}

{text}
"""


def new(root: Path, *, type_: str, title: str, text: str | None = None, ticket: str | None = None,
        affects: list[str] | None = None) -> Path:
    if type_ not in TYPES:
        raise EkitError(f"--type must be one of {', '.join(TYPES)}")
    title = " ".join((title or "").split())
    if not title:
        raise EkitError('A short title is required: --title "Unread badge does not clear"')
    specs = root / "specs"
    known = {d.name for d in specs.iterdir() if d.is_dir()} if specs.is_dir() else set()
    feats: list[str] = []
    for a in affects or []:
        for f in (x.strip() for x in a.split(",")):
            if not f:
                continue
            hit = [k for k in known if k == f or k.startswith(f + "-")]
            if len(hit) != 1:
                raise EkitError(f"--affects {f}: not one feature folder in specs/. Known: {', '.join(sorted(known)) or 'none'}")
            feats.append(hit[0])
    taken = [int(CR_DIR_RE.match(d.name).group(1)) for d in all_dirs(root)]
    num = (max(taken) + 1) if taken else 1
    cid = cr_id(num)
    d = root / REQ_DIR / f"cr-{num:04d}-{slugify(title)}"
    d.mkdir(parents=True, exist_ok=False)
    who, at = _who(root), _now()
    body = (text or "").replace("\r\n", "\n").strip() or PLACEHOLDER
    (d / "request.md").write_text(REQUEST_TEMPLATE.format(cid=cid, title=title, type=type_, ticket=ticket or "-",
                                                         at=at, by=who, marker=REQUEST_MARKER, text=body),
                                  encoding="utf-8", newline="\n")
    data: dict[str, Any] = {
        "apiVersion": "ekit/v1", "kind": "ChangeRequest", "id": cid, "type": type_, "title": title,
        "ticket": ticket or None, "recorded_by": who, "recorded_at": at,
        "affects": {"features": sorted(set(feats)), "paths": []},
        "supersedes": [],
    }
    if type_ == "bug":
        data["bug"] = {"observed": "", "expected": "", "reproduction": ""}
    dump_yaml(data, d / "change.yaml")
    logbook.append(root, {"kind": "state.change.new", "change": cid, "type": type_, "dir": d.relative_to(root).as_posix(),
                          "affects": data["affects"]["features"], "via": logbook.via(), "actor": logbook.actor(root)})
    return d


def request_text(cr_dir: Path) -> str:
    p = cr_dir / "request.md"
    if not p.is_file():
        return ""
    text = p.read_text(encoding="utf-8")
    _, _, after = text.partition(REQUEST_MARKER)
    return after.strip()


# --------------------------------------------------------------------------- candidates
_STOP_WORDS = """
a an and are as at be but by can do does doesnt don dont for from has have i if in into is it its of
on or our should so than that the their then there these this to up us was we were when where which
while who will with would you your user users not no after before again also any all
"""
_STOP = frozenset(_STOP_WORDS.split())


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9]{2,}", text.lower()) if w not in _STOP}


def candidates(root: Path, text: str, limit: int = 5) -> list[tuple[str, int, list[str]]]:
    """Rank existing feature folders by word overlap of the request with their spec, scenarios and
    folder name. Deterministic and cheap; a hint for the agent, never a decision."""
    want = _words(text)
    if not want:
        return []
    out = []
    specs = root / "specs"
    for d in sorted(specs.iterdir()) if specs.is_dir() else []:
        if not d.is_dir() or d.name.startswith("000-"):
            continue
        corpus = d.name.replace("-", " ")
        for f in [d / "spec.md", *sorted((d / "features").glob("*.feature"))] if (d / "features").is_dir() else [d / "spec.md"]:
            if f.is_file():
                corpus += "\n" + f.read_text(encoding="utf-8", errors="replace")
        hits = sorted(want & _words(corpus))
        if hits:
            out.append((d.name, len(hits), hits[:8]))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out[:limit]


# --------------------------------------------------------------------------- retire
_BLOCK_START = re.compile(r"^\s*(Scenario|Scenario Outline|Scenario Template|Example|Rule)\s*:")
_TAG_LINE = re.compile(r"^\s*@")


def scenario_blocks(text: str) -> tuple[str, dict[str, str]]:
    """Split a feature file into (preamble, {SCN-id: block text}). A block runs from its tag lines to
    the line before the next scenario's tag lines. Untagged blocks stay in the preamble key order."""
    lines = text.replace("\r\n", "\n").split("\n")
    starts = []
    for i, line in enumerate(lines):
        if _BLOCK_START.match(line):
            j = i
            while j > 0 and _TAG_LINE.match(lines[j - 1]):
                j -= 1
            starts.append(j)
    if not starts:
        return text, {}
    pre = "\n".join(lines[:starts[0]])
    blocks: dict[str, str] = {}
    bounds = starts + [len(lines)]
    for k, s in enumerate(starts):
        block = "\n".join(lines[s:bounds[k + 1]]).rstrip() + "\n"
        ids = re.findall(r"@(SCN-\d{3}-\d{2})\b", "\n".join(lines[s:s + 10]))
        key = ids[0] if ids else f"__untagged_{k}"
        blocks[key] = block
    return pre, blocks


def retire(project: Any, feature: str, scenarios: list[str], *, change: str, reason: str) -> list[str]:
    """Record that scenarios of a delivered (frozen) feature are retired by a change request.

    The person has already removed the scenarios from the feature's `.feature` file(s). This checks
    that exactly those scenarios are gone and every other scenario is byte-identical to the committed
    (fingerprinted) version, then writes a `rebase` ledger entry with the new fingerprints and
    re-applies the freeze. Returns messages."""
    from . import freeze
    from .checks import _sha
    root = project.root
    if not reason.strip():
        raise EkitError('A reason is required: --reason "..."')
    cr_dir = find(root, change)
    data = load(cr_dir)
    cid = data.get("id") or cr_id(CR_DIR_RE.match(cr_dir.name).group(1))
    bad = [s for s in scenarios if not SCN_RE.match(s)]
    if bad or not scenarios:
        raise EkitError(f"Scenario ids look like SCN-003-04; got: {', '.join(bad) or 'none'}")
    sup = {str(s) for s in (data.get("supersedes") or [])}
    missing = [s for s in scenarios if s not in sup]
    if missing:
        raise EkitError(f"{cid} does not list {', '.join(missing)} under `supersedes:` in {cr_dir.name}/change.yaml. "
                        "The change request must say what it supersedes before a person retires it.")
    ledger = root / ".ekit" / "ledger" / f"{feature}.yaml"
    if not ledger.is_file():
        raise EkitError(f"{feature} has no ledger: nothing is frozen there, edit its scenarios normally.")
    led = load_yaml(ledger) or {}
    entries = led.get("entries") or []
    base = next((e for e in reversed(entries) if e.get("phase") in ("red", "rebase") and e.get("fingerprints")), None)
    if base is None:
        raise EkitError(f"{feature}: no red entry with fingerprints to rebase from.")
    fp = dict(base["fingerprints"])
    prefix = f"specs/{feature}/features/"
    feature_files = [rel for rel in fp if rel.startswith(prefix) and rel.endswith(".feature")]
    removed: set[str] = set()
    new_fp = dict(fp)
    for rel in feature_files:
        now_p = root / rel
        raw = _show_head(root, rel)
        if raw is None:
            raise EkitError(f"{rel}: not committed at HEAD; commit the feature before retiring scenarios.")
        if hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest() != fp[rel]:
            raise EkitError(f"{rel}: the committed version differs from what was frozen; resolve that first "
                            f"(`ekit gate green --feature {feature}` shows it).")
        old_text = raw.decode("utf-8")
        if not now_p.is_file():
            raise EkitError(f"{rel}: deleted. Remove the retired scenarios from the file, never the file itself.")
        now_text = now_p.read_text(encoding="utf-8")
        o_pre, o_blocks = scenario_blocks(old_text)
        n_pre, n_blocks = scenario_blocks(now_text)
        if o_pre.strip() != n_pre.strip():
            raise EkitError(f"{rel}: the Feature header or Background changed; retiring may only remove scenarios.")
        for sid, block in n_blocks.items():
            if sid not in o_blocks:
                raise EkitError(f"{rel}: {sid} is new. New behaviour goes in the change request's own feature folder.")
            if block.rstrip() != o_blocks[sid].rstrip():
                raise EkitError(f"{rel}: {sid} changed. Retiring removes whole scenarios; every other one stays byte-identical.")
        gone = set(o_blocks) - set(n_blocks)
        stray = sorted(gone - set(scenarios))
        if stray:
            raise EkitError(f"{rel}: also removed {', '.join(stray)}, which you did not name. Name every retired scenario.")
        removed |= gone
        new_fp[rel] = _sha(now_p)
    not_found = sorted(set(scenarios) - removed)
    if not_found:
        raise EkitError(f"{', '.join(not_found)} still present in {feature} (or never there). Remove the scenario(s) "
                        f"from specs/{feature}/features/*.feature yourself, then run this again.")
    entry = {
        "phase": "rebase", "at": _now(), "by": _who(root), "change": cid, "retired": sorted(removed),
        "reason": reason.strip(), "git_head": git(root, "rev-parse", "HEAD"), "fingerprints": new_fp,
    }
    if base.get("contract"):
        entry["contract"] = base["contract"]
    entries.append(entry)
    led["entries"] = entries
    dump_yaml(led, ledger)
    rules = freeze.freeze_feature(root, feature, new_fp) if feature in freeze.load_state(root).get("frozen", {}) else []
    logbook.append(root, {"kind": "state.change.retire", "feature": feature, "change": cid, "retired": sorted(removed),
                          "reason": reason.strip(), "via": logbook.via(), "actor": logbook.actor(root)})
    msgs = [f"{feature}: retired {', '.join(sorted(removed))} for {cid}; ledger rebased ({len(new_fp)} fingerprint(s))."]
    if rules:
        msgs.append("Freeze re-applied. Restart OpenCode.")
    msgs.append(f'Commit it: git add -A && git commit -m "test({feature[:3]}): retire {", ".join(sorted(removed))} ({cid})"')
    return msgs


def _show_head(root: Path, rel: str) -> bytes | None:
    exe = shutil.which("git")
    if not exe:
        return None
    res = subprocess.run([exe, "show", f"HEAD:{rel}"], cwd=root, capture_output=True, check=False)
    return res.stdout if res.returncode == 0 else None


def retired_scenarios(root: Path) -> dict[str, str]:
    """{SCN-id: CR-id} for every scenario retired by a `rebase` ledger entry."""
    out: dict[str, str] = {}
    led_dir = root / ".ekit" / "ledger"
    for p in sorted(led_dir.glob("*.yaml")) if led_dir.is_dir() else []:
        for e in ((load_yaml(p) or {}).get("entries") or []):
            if e.get("phase") == "rebase":
                for s in e.get("retired") or []:
                    out[str(s)] = str(e.get("change"))
    return out


# --------------------------------------------------------------------------- listing
def phase_of(root: Path, features: list[str]) -> str:
    if not features:
        return "intake"
    best = "spec"
    for f in features:
        led = root / ".ekit" / "ledger" / f"{f}.yaml"
        phases = {e.get("phase") for e in ((load_yaml(led) or {}).get("entries") or [])} if led.is_file() else set()
        if "green" in phases:
            return "green"
        if "red" in phases:
            best = "red"
    return best


def summary_rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for d in all_dirs(root):
        try:
            data = load(d)
        except EkitError as exc:
            rows.append({"id": d.name, "error": str(exc)})
            continue
        feats = features_of(root, d)
        rows.append({"id": data.get("id"), "dir": d.name, "type": data.get("type"), "title": data.get("title"),
                     "affects": affected_features(data), "features": feats, "phase": phase_of(root, feats),
                     "supersedes": list(data.get("supersedes") or [])})
    return rows
