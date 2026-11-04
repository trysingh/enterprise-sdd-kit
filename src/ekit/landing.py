"""Landing-zone evidence: record a passing `ekit gate baseline` and tell `ekit status` whether it still holds.

The record (`.ekit/ledger/baseline.yaml`, commit it) fingerprints what the verdict depended on:
the platform conformance record, the pinned kit, and which profiles were active (waves can turn a
profile on later; its landing zone and platform NFRs are then required, so the record goes stale).
Reading it is cheap, so `ekit status` never re-runs lint or the gate itself.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

from .project import EKIT_DIR, dump_yaml, git, load_yaml

RECORD = ".ekit/ledger/baseline.yaml"
CONFORMANCE = "docs/engineering/baseline-conformance.md"


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() if path.is_file() else None


def fingerprint(project: Any) -> dict[str, Any]:
    from .kitsource import read_lock
    lock = read_lock(project.root) or {}
    plan = getattr(project, "wave_plan", None)
    return {
        "conformance_sha256": _sha(project.root / CONFORMANCE),
        "kit_sha256": lock.get("sha256"),
        "active_profiles": sorted(p.id for p in project.active_profiles),
        "wave": plan.current if plan is not None else None,
    }


def record(project: Any, path: str = RECORD) -> Path | None:
    """Write the record after a passing baseline gate. Unchanged evidence is not rewritten (no churn)."""
    from . import __version__
    dest = project.root / path
    fp = fingerprint(project)
    head = git(project.root, "rev-parse", "HEAD")
    if dest.is_file():
        old = load_yaml(dest) or {}
        if old.get("fingerprint") == fp and old.get("git_head") == head:
            return None
    dump_yaml({
        "apiVersion": "ekit/v1",
        "kind": "BaselineRecord",
        "result": "passed",
        "at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "git_head": head,
        "kit_version": project.kit.version,
        "ekit_version": __version__,
        "fingerprint": fp,
    }, dest)
    return dest


def status(project: Any) -> tuple[str, str]:
    """('passed' | 'stale' | 'not run', detail) for `ekit status` and `ekit doctor`."""
    p = project.root / RECORD
    if not p.is_file():
        return "not run", "no passing `ekit gate baseline` recorded (ekit >= 0.2.1 records it)"
    rec = load_yaml(p) or {}
    old, now = rec.get("fingerprint") or {}, fingerprint(project)
    reasons = []
    if old.get("conformance_sha256") != now["conformance_sha256"]:
        reasons.append(f"{CONFORMANCE} changed")
    if old.get("kit_sha256") != now["kit_sha256"]:
        reasons.append("the pinned kit changed (ekit upgrade)")
    if old.get("active_profiles") != now["active_profiles"]:
        added = sorted(set(now["active_profiles"]) - set(old.get("active_profiles") or []))
        reasons.append(f"newly active: {', '.join(added)}" if added else "active profiles changed")
    head = str(rec.get("git_head") or "")[:7] or "no git"
    when = str(rec.get("at") or "")[:10]
    if reasons:
        return "stale", f"passed {when} at {head}, but {'; '.join(reasons)}: run `ekit gate baseline`"
    wave = f", wave {now['wave']}" if now.get("wave") else ""
    return "passed", f"{when} at {head} (kit {rec.get('kit_version')}{wave})"


def smoke_summary(project: Any) -> str | None:
    """The landing zone's own scenarios (specs/000-*), e.g. the health / correlation-id smoke test."""
    from . import gherkin
    dirs = [d for d in (project.root / "specs").glob("000-*") if d.is_dir()] if (project.root / "specs").is_dir() else []
    if not dirs:
        return None
    ids: list[str] = []
    for d in dirs:
        for f in gherkin.parse_dir(d / "features"):
            for s in f.scenarios:
                ids += gherkin.scn_tags(s.tags)
    names = ", ".join(d.name for d in sorted(dirs))
    return f"{names}: {len(ids)} smoke scenario(s) {', '.join('@' + i for i in sorted(set(ids)))} (must stay green in every feature's green run)"


__all__ = ["RECORD", "fingerprint", "record", "status", "smoke_summary", "EKIT_DIR"]
