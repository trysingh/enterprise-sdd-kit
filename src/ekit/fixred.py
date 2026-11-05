"""`ekit fix-red`: the human-only, reviewed shortcut for "this frozen test's own glue is wrong,
not the implementation" — the exact situation found fixing conversation-persistence by hand
(stash, unfreeze, revert source, red, commit, restore, green).

What it automates: unfreezing, temporarily putting the feature's production source back to its
state at the last red commit (not via `git stash`, which has nothing to grab once that source is
already committed — the common case by the time a frozen-test bug is found), running `ekit gate
red`, and restoring the source whatever the outcome.

What it never does: commit anything. A clean `ekit gate red` here still means a human reviews the
test diff and runs the commit themselves, same as every other step in this pipeline. It is also
denied to the agent's shell tool, same as `ekit unfreeze` — this removes toil for the person who
already has to make this call, not a new thing an agent can decide to do.

Precondition: the feature's source dirs must be clean (`git status --porcelain` empty) before
starting. That lets restoration be exact (`git checkout HEAD -- <dirs>` undoes the temporary
revert bit for bit) without a side backup of arbitrary uncommitted edits. If it's dirty, this
refuses rather than guess what of yours is safe to touch.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import freeze
from .project import EkitError, Project, load_yaml


def _run(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError as exc:
        raise EkitError(f"git {' '.join(args)} failed: {exc.stderr.strip() or exc.stdout.strip()}") from None
    except OSError as exc:
        raise EkitError(f"git {' '.join(args)} failed: {exc}") from None


def _last_red_commit(root: Path, feature: str) -> str:
    ledger = root / ".ekit" / "ledger" / f"{feature}.yaml"
    if not ledger.is_file():
        raise EkitError(f"No ledger {ledger.relative_to(root)}: nothing recorded as red for {feature}.")
    reds = [e for e in ((load_yaml(ledger) or {}).get("entries") or []) if e.get("phase") == "red"]
    if not reds:
        raise EkitError(f"No red entry in {ledger.relative_to(root)}.")
    head = reds[-1].get("git_head")
    if not head:
        raise EkitError("The last red entry has no recorded git_head (an older ekit recorded it); "
                         "revert the source by hand and run `ekit unfreeze` / `ekit gate red` directly.")
    return head


def _added_since(root: Path, red_commit: str, dirs: list[str]) -> list[str]:
    """Files under `dirs` that exist now but did not exist at `red_commit` — `git checkout
    <red_commit> -- <dirs>` can't remove these (they're not in that tree), so they're moved aside
    and moved back, rather than reverted."""
    out = _run(root, "diff", "--no-renames", "--name-status", red_commit, "HEAD", "--", *dirs)
    added = []
    for line in out.splitlines():
        status, _, rel = line.partition("\t")
        if status.strip() == "A" and rel:
            added.append(rel.strip())
    return added


def _revert_scope(project: Any, feature: str) -> list[str]:
    """What to revert to the last-red commit. Golden projects (0.3.0) keep each feature's code in its
    own package, so only that package is reverted — not the whole source tree, which on a project with
    several features could strip shared code added since (the limit 0.2.4 could only explain)."""
    from . import golden
    root = project.root
    pkg = golden.feature_package(golden.for_project(project), feature)
    if pkg and (root / pkg).is_dir():
        return [pkg]
    return [d for d in freeze.source_dirs(project) if (root / d).is_dir()]


def fix_red(project: Any, feature: str, reason: str) -> tuple[bool, str]:
    """Unfreeze, temporarily revert the feature's source to its last-red state, run `ekit gate
    red`, restore the source either way. Returns (clean, report) — `clean` is whether red came
    back clean (every scenario of this feature failed, none errored); `report` is `ekit gate
    red`'s own text output, for the caller to print as-is."""
    root = project.root
    state = freeze.load_state(root)
    if feature not in state["frozen"]:
        raise EkitError(f"{feature} is not frozen — nothing to fix. (New feature? Just fix the test and `ekit gate red`.)")
    dirs = _revert_scope(project, feature)
    if not dirs:
        raise EkitError("No active profile's production source directory exists yet (layout.source); "
                         "revert it yourself (`git stash`/`git checkout`), then `ekit unfreeze` and `ekit gate red`.")
    dirty = _run(root, "status", "--porcelain", "--", *dirs).strip()
    if dirty:
        raise EkitError(f"{', '.join(dirs)} has uncommitted changes:\n{dirty}\n"
                         "Commit or stash them yourself first — `ekit fix-red` only reverts committed source, "
                         "cleanly, so it can restore it exactly afterwards.")
    red_commit = _last_red_commit(root, feature)
    narrow = freeze.source_patterns(project)
    freeze.unfreeze_feature(root, feature, reason, narrow_src=narrow)

    backup = Path(tempfile.mkdtemp(prefix="ekit-fixred-"))
    added = _added_since(root, red_commit, dirs)
    for rel in added:
        src, dest = root / rel, backup / rel
        if src.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
    # Only ask git to check out a dir from a given commit if it holds a tracked file there — an
    # empty dir (nothing committed in it, e.g. a stack's unused frontend source dir) or one that's
    # new since red (created by this feature's own implementation) has nothing to check out, and
    # `git checkout <rev> -- <path>` errors on a pathspec that matches nothing in that tree. This
    # applies on the way in (revert to red_commit) and on the way out (restore to HEAD) alike.
    def _tracked(rev: str, d: str) -> bool:
        return bool(_run(root, "ls-tree", "-r", "--name-only", rev, "--", d).strip())

    revertible = [d for d in dirs if _tracked(red_commit, d)]
    restorable = [d for d in dirs if _tracked("HEAD", d)]
    try:
        if revertible:
            _run(root, "checkout", red_commit, "--", *revertible)
        from . import gates
        res, notes = gates.run_gate(Project.load(root), "red", feature=feature)
        report = gates.render_text(res, notes)
        clean = res.passed
    finally:
        if restorable:
            _run(root, "checkout", "HEAD", "--", *restorable)
        for rel in added:
            dest, target = backup / rel, root / rel
            if dest.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dest), str(target))
        shutil.rmtree(backup, ignore_errors=True)
    return clean, report
