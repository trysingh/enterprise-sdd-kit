"""Deterministic answers to questions the command texts used to leave to the model (ekit 0.3.0).

* `current`: which feature folder a command works on. 0.2.5 found an agent that, given empty
  `$ARGUMENTS`, picked the *example* name printed in the command text (`001-user-admin`) as the
  feature to implement. 0.2.5 reworded the text; 0.3.0 removes the judgement: the commands run
  `ekit feature current --for red|implement "$ARGUMENTS"`, which prints exactly one real folder or
  fails with the list of real candidates. It never returns a `000-*` folder (landing zone / reference).
* `new_adr`: the next free ADR number, so two ADRs never share one (0.2.1 found two `0001`s).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .project import FEATURE_DIR_RE, EkitError, git, load_yaml

PHASES = ("red", "implement", "any")


def _phases(root: Path, feature: str) -> set[str]:
    ledger = root / ".ekit" / "ledger" / f"{feature}.yaml"
    if not ledger.is_file():
        return set()
    return {str(e.get("phase")) for e in ((load_yaml(ledger) or {}).get("entries") or [])}


def _has_scenarios(d: Path) -> bool:
    return any((d / "features").glob("*.feature")) if (d / "features").is_dir() else False


def _ready(root: Path, d: Path, phase: str) -> bool:
    done = _phases(root, d.name)
    if phase == "red":
        return _has_scenarios(d) and "red" not in done
    if phase == "implement":
        return "red" in done and "green" not in done
    return True


def current(project: Any, name: str | None, *, phase: str = "any") -> str:
    if phase not in PHASES:
        raise EkitError(f"--for must be one of {', '.join(PHASES)}")
    root = project.root
    real = [d for d in project.feature_dirs() if not d.name.startswith("000-")]
    names = ", ".join(d.name for d in real) or "none yet"
    given = (name or "").strip().strip("\"'")
    if given and given != "$ARGUMENTS":
        m = re.match(r"^(\d{3})(?:-|$)", given)
        hits = [d for d in real if d.name == given or (m and given == m.group(1) and d.name.startswith(given + "-"))]
        if given.startswith("000"):
            raise EkitError(f"{given} is the landing zone or the reference slice, never a feature to work on. "
                            f"Real features: {names}")
        if len(hits) == 1:
            return hits[0].name
        raise EkitError(f"'{given}' does not name a feature folder in specs/. Real features: {names}. "
                        "Ask the user which one; never pick an example name")
    for cand in (os.environ.get("SPECIFY_FEATURE"), git(root, "rev-parse", "--abbrev-ref", "HEAD")):
        if cand and FEATURE_DIR_RE.match(cand) and not cand.startswith("000-") and (root / "specs" / cand).is_dir():
            return cand
    ready = [d.name for d in real if _ready(root, d, phase)]
    if len(ready) == 1:
        return ready[0]
    what = {"red": "has scenarios but no red record", "implement": "is recorded red but not green",
            "any": "exists"}[phase]
    if not ready:
        raise EkitError(f"No feature {what}. Real features: {names}. Stop and tell the user")
    raise EkitError(f"Several features {what}: {', '.join(ready)}. Ask the user which one (pass it as the argument)")


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "decision"


ADR_TEMPLATE = """# ADR-{num}: {title}

**Status**: Proposed

## Context
[What forces this decision: requirement, NFR, constraint.]

## Decision
[What we decided.]

## Consequences
[What becomes easier or harder; follow-up work.]
"""


def new_adr(root: Path, title: str, decision: str | None = None) -> Path:
    title = title.strip()
    if not title:
        raise EkitError('ekit adr new "Title of the decision"')
    d = root / "docs" / "adr"
    d.mkdir(parents=True, exist_ok=True)
    taken = [int(m.group(1)) for f in d.glob("*.md") if (m := re.match(r"^(\d{4})-", f.name))]
    num = f"{(max(taken) + 1) if taken else 1:04d}"
    path = d / f"{num}-{_slug(title)}.md"
    text = ADR_TEMPLATE.format(num=num, title=title)
    if decision:
        decision = decision.strip()
        dtitle = ""
        if (root / "docs" / "design" / "design.yaml").is_file():
            from .design import load_design
            found = [x for x in load_design(root).get("decisions") or [] if isinstance(x, dict) and str(x.get("id")) == decision]
            if not found:
                raise EkitError(f"design.yaml has no decision {decision} (see `decisions:` in docs/design/design.yaml)")
            dtitle = str(found[0].get("title") or "")
        ref = f"**Decision**: {decision}" + (f" ({dtitle})" if dtitle else "")
        text = text.replace("**Status**: Proposed\n", f"**Status**: Proposed\n\n{ref} in docs/design/design.yaml\n", 1)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path
