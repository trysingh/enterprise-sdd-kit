"""The baseline ratchet (ekit 0.6.0): `.ekit/baseline-enforced.yaml`.

In a brownfield project the platform NFRs are accepted as-is (`Inherited`) until a person decides
otherwise. `ekit baseline enforce <NFR-ID> --reason "..."` records that decision: from then on the
gate requires that NFR to be Addressed, N/A or Waived (with an ADR); Inherited, Gap or no row fail.

One way by design: there is no command to un-enforce. Removing an entry is a hand edit of the file,
which should be accompanied by an ADR. Entries record who, when and why.
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Any

from .project import EkitError, dump_yaml, git, load_yaml

ENFORCED = ".ekit/baseline-enforced.yaml"


def actor(root: Path) -> str:
    """git user.name, else the USER / USERNAME environment variable."""
    return git(root, "config", "user.name") or os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


def load(root: Path) -> list[dict[str, Any]]:
    p = root / ENFORCED
    if not p.is_file():
        return []
    data = load_yaml(p) or {}
    return [e for e in (data.get("enforced") or []) if isinstance(e, dict) and e.get("id")]


def enforced_ids(root: Path) -> set[str]:
    return {str(e["id"]) for e in load(root)}


def platform_ids(project: Any) -> list[str]:
    return [n["id"] for n in project.kit.nfr_catalog().get("nfrs", []) if n.get("scope") == "platform"]


def enforce(project: Any, nids: list[str], reason: str) -> list[str]:
    """Append entries for `nids`. Returns one message per id. Nothing is written if any id is invalid."""
    if not nids:
        raise EkitError('ekit baseline enforce <NFR-ID> [<NFR-ID> ...] --reason "..."')
    if not (reason or "").strip():
        raise EkitError('--reason is required (it is recorded): ekit baseline enforce SEC-01 --reason "..."')
    valid = platform_ids(project)
    bad = [i for i in nids if i not in valid]
    if bad:
        raise EkitError(f"not a platform-scope NFR id: {', '.join(bad)} (valid: {', '.join(valid)})")
    root = project.root
    entries = load(root)
    have = {str(e["id"]) for e in entries}
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    who = actor(root)
    msgs = []
    for nid in dict.fromkeys(nids):
        if nid in have:
            msgs.append(f"{nid}: already enforced")
            continue
        entries.append({"id": nid, "by": who, "at": now, "reason": reason.strip()})
        msgs.append(f"{nid}: enforced")
    dump_yaml({"enforced": entries}, root / ENFORCED)
    return msgs
