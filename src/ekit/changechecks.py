"""ekit 0.5.0: checks for change requests (bug fixes and features taken from the prompt).

All of them are no-ops for ordinary PRD folders and features, so they sit in the normal gates.

* `change.valid` (intake, ready): change.yaml is complete, the request is kept verbatim, the
  features it affects exist, the scenarios it supersedes are real. With `ready: true` it also
  refuses `[TBD` in the bug facts.
* `change.bug_reproduced` (red): a bug is reproduced against the committed production code, which
  red left untouched, and fails on an assertion, never on a 501 stub or NotImplementedError.
* `change.supersedes_retired` (red as a warning, green as an error): every scenario the change
  supersedes has been retired by a person (`ekit change retire`), or the old frozen scenario would
  keep asserting the old behaviour and the suite could never be green.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import changes, gherkin
from .checks import Finding, GateContext, _active, _feature_scn_ids, check
from .project import git, load_yaml

_GOT_STATUS = re.compile(r"expected (\d{3}), got (\d{3})\b")
_STUB_MARKERS = ("NotImplementedError", "not_implemented", "Not Implemented")


def _scn_index(root: Path, skip: set[str]) -> dict[str, str]:
    """{SCN-id: feature folder} for every tagged scenario in specs/, except the skipped folders."""
    out: dict[str, str] = {}
    specs = root / "specs"
    for d in sorted(specs.iterdir()) if specs.is_dir() else []:
        if not d.is_dir() or d.name in skip:
            continue
        for ff in gherkin.parse_dir(d / "features"):
            for sc in ff.scenarios:
                for sid in gherkin.scn_tags(sc.tags):
                    out[sid] = d.name
    return out


@check("change.valid")
def change_valid(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    d = ctx.path(w["dir"])
    if not changes.is_change_dir(d):
        return []
    root = ctx.project.root
    out: list[Finding] = []
    data = load_yaml(d / "change.yaml") or {}
    if not isinstance(data, dict):
        return [Finding("error", f"{d.name}/change.yaml is not a mapping")]
    m = changes.CR_DIR_RE.match(d.name)
    want_id = changes.cr_id(m.group(1)) if m else None
    if want_id and data.get("id") != want_id:
        out.append(Finding("error", f"change.yaml id '{data.get('id')}' != folder {d.name} ({want_id})"))
    if data.get("type") not in changes.TYPES:
        out.append(Finding("error", f"change.yaml type must be one of {', '.join(changes.TYPES)}"))
    if not str(data.get("title") or "").strip():
        out.append(Finding("error", "change.yaml: 'title' is required"))
    req = changes.request_text(d)
    if not req or changes.PLACEHOLDER in req:
        out.append(Finding("error", f"{d.name}/request.md has no request text: paste the user's request verbatim "
                                    f"under '{changes.REQUEST_MARKER}'"))
    known = {p.name for p in (root / "specs").iterdir() if p.is_dir()} if (root / "specs").is_dir() else set()
    affects = changes.affected_features(data)
    for f in affects:
        if f not in known:
            out.append(Finding("error", f"change.yaml affects '{f}', which is not a folder in specs/"))
    if data.get("type") in ("bug", "enhancement") and not affects and not (data.get("affects") or {}).get("paths"):
        out.append(Finding("warn", f"a {data.get('type')} changes existing behaviour, but change.yaml names no affected "
                                   "feature or path (`ekit change candidates \"<request>\"` suggests some)"))
    if data.get("type") == "bug":
        bug = data.get("bug") or {}
        for key in ("observed", "expected"):
            val = str(bug.get(key) or "").strip()
            if not val:
                out.append(Finding("error", f"change.yaml bug.{key} is empty: state the {key} behaviour, or "
                                            "`[TBD: OQ-xxx]` with a question in open-questions.yaml"))
            elif w.get("ready") and "[TBD" in val:
                out.append(Finding("error", f"change.yaml bug.{key} is still {val}: answer the question first"))
    own = set(changes.features_of(root, d))
    index = _scn_index(root, own)
    retired = changes.retired_scenarios(root)
    for sid in data.get("supersedes") or []:
        sid = str(sid)
        if not changes.SCN_RE.match(sid):
            out.append(Finding("error", f"change.yaml supersedes '{sid}': not a scenario id (SCN-003-04)"))
        elif sid not in index and sid not in retired:
            out.append(Finding("error", f"change.yaml supersedes {sid}, which no feature in specs/ defines"))
    prd = d / "prd.md"
    if prd.is_file():
        feats = sorted(set(re.findall(r"^#{2,4}\s*(FEAT-\d{2})\b", prd.read_text(encoding="utf-8"), re.MULTILINE)))
        if len(feats) > 1:
            out.append(Finding("warn", f"{d.name}/prd.md has {len(feats)} features ({', '.join(feats)}). A change "
                                       "request is normally one feature; a larger one belongs in /speckit.esdlc.brd"))
    return out


@check("change.bug_reproduced")
def bug_reproduced(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    hit = changes.for_feature(ctx.project.root, ctx.feature_dir)
    if not hit or hit[1].get("type") != "bug":
        return []
    cid = hit[1].get("id")
    out: list[Finding] = []
    from .freeze import source_dirs
    dirs = [s for s in source_dirs(ctx.project) if (ctx.project.root / s).exists()]
    if dirs:
        dirty = git(ctx.project.root, "status", "--porcelain", "--", *dirs)
        if dirty is None:
            out.append(Finding("warn", "git unavailable: cannot prove the bug was reproduced against committed code"))
        elif dirty:
            files = ", ".join(line.split(maxsplit=1)[-1] for line in dirty.splitlines()[:5])
            out.append(Finding("error", f"{cid} is a bug: red reproduces it against the committed production code, "
                                        f"so production source must be untouched at red. Changed: {files}. Revert those "
                                        "changes (no stubs, no partial fix), keep only test changes, and rerun "
                                        "`ekit gate red`."))
    want = _feature_scn_ids(ctx, w["dir"])
    reports = [p.root / p.bdd["report"] for p in _active(ctx) if p.runs_bdd and p.bdd.get("report")]
    elements = gherkin.read_cucumber_elements([r for r in reports if r.is_file()])
    for sid in want:
        for el in elements.get(sid, []):
            step = next((s for s in el.get("steps", []) if (s.get("result") or {}).get("status") == "failed"), None)
            if step is None:
                continue
            msg = (step.get("result") or {}).get("error_message") or ""
            m = _GOT_STATUS.search(msg)
            if (m and m.group(2) == "501") or any(k in msg for k in _STUB_MARKERS):
                name = f"{(step.get('keyword') or '').strip()} {step.get('name') or ''}".strip()
                out.append(Finding("error", f"{sid}: failed on a stub (501 / not implemented) at step '{name}'. {cid} is "
                                            "a bug in code that exists: the scenario must fail on an assertion that shows "
                                            "the observed (wrong) behaviour, against the real code"))
                break
    return out


@check("change.supersedes_retired")
def supersedes_retired(ctx: GateContext, w: dict[str, Any]) -> list[Finding]:
    root = ctx.project.root
    hit = changes.for_feature(root, ctx.feature_dir)
    if not hit:
        return []
    cr_dir, data = hit
    sup = [str(s) for s in (data.get("supersedes") or [])]
    if not sup:
        return []
    index = _scn_index(root, set(changes.features_of(root, cr_dir)))
    out = []
    for sid in sup:
        if sid in index:
            feat = index[sid]
            out.append(Finding("error", f"{sid} in {feat} asserts the behaviour {data.get('id')} changes and is not retired. "
                                        f"A person removes it from specs/{feat}/features/ and runs "
                                        f"`ekit change retire {feat} {sid} --by {data.get('id')} --reason \"...\"`"))
    return out
