"""Golden landing zones (ekit 0.3.0): a pre-built, reviewed landing zone per stack.

What it does
  * `install`: copy the stack's golden tree (kit/golden/<stack>/tree) into a greenfield project,
    rendering the project name, and fingerprint every installed file in `.ekit/golden.lock.yaml`.
  * Freeze the golden *core* (manifest `frozen:`) against agent edits, through the same
    `permission.edit` mechanism as frozen red tests (freeze.py, state key `baseline`).
  * `drift`: which core files differ from the lock — the evidence `BASE-GOLDEN-INTACT` and
    `GREEN-GOLDEN-INTACT` judge. A person changes the core with `ekit baseline unfreeze`, edits, and
    `ekit baseline accept` (re-fingerprints, re-freezes; both audited).
  * `merge_upgrade`: a kit upgrade that brings a new golden revision is applied as a three-way merge
    (old golden -> new golden, onto the project's files) with `git merge-file`; conflicts are left
    with markers, listed in the lock, and block the baseline gate until a person resolves them.
  * `feature_package`: the one package a Spec Kit feature folder's code lives in (`f003_slug`), which
    `ekit fix-red` uses to scope its revert to that feature alone.

Everything here is deterministic: no model is involved in installing, freezing or merging the core.
"""
from __future__ import annotations

import datetime as dt
import fnmatch
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .project import EkitError, dump_yaml, load_yaml

LOCK = ".ekit/golden.lock.yaml"
MANIFEST = "golden.yaml"
TREE = "tree"
SKIP_POST_INSTALL_ENV = "EKIT_SKIP_POST_INSTALL"
CONFLICT_RE = re.compile(r"^(<<<<<<< |>>>>>>> )", re.M)
MERGE_LABELS = ("project", "golden-old", "golden-new")


# --------------------------------------------------------------------------- manifest
@dataclass
class Golden:
    path: Path                 # kit/golden/<stack>
    manifest: dict[str, Any]

    @property
    def version(self) -> str:
        return str((self.manifest.get("metadata") or {}).get("version", "0.0.0"))

    @property
    def stack(self) -> str:
        return str((self.manifest.get("metadata") or {}).get("stack", ""))

    @property
    def tree(self) -> Path:
        return self.path / TREE

    @property
    def frozen(self) -> list[str]:
        return list(self.manifest.get("frozen") or [])

    @property
    def seams(self) -> dict[str, str]:
        return dict(self.manifest.get("seams") or {})

    @property
    def exemplar(self) -> dict[str, str]:
        return dict(self.manifest.get("exemplar") or {})

    @property
    def agent_rules(self) -> str:
        return str(self.manifest.get("agent_rules") or "").strip()


def for_stack(kit: Any, stack: str) -> Golden | None:
    """The golden landing zone the kit offers for this stack, or None."""
    rel = ((kit.stacks or {}).get(stack) or {}).get("golden")
    if not rel:
        return None
    path = kit.path / rel
    if not (path / MANIFEST).is_file():
        raise EkitError(f"Kit stack {stack} names golden '{rel}' but {path / MANIFEST} does not exist.")
    return Golden(path, load_yaml(path / MANIFEST) or {})


def for_project(project: Any) -> Golden | None:
    if not is_golden(project):
        return None
    return for_stack(project.kit, project.stack_id)


def is_golden(project: Any) -> bool:
    return str(((getattr(project, "config", None) or {}).get("baseline") or {}).get("mode")) == "golden"


# --------------------------------------------------------------------------- rendering
def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "app"


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def sha_file(path: Path) -> str | None:
    return _sha_bytes(path.read_bytes()) if path.is_file() else None


def materialize(golden: Golden, project_name: str) -> dict[str, bytes]:
    """Target path -> content, exactly as it would be installed for this project name."""
    renames = {str(k): str(v) for k, v in (golden.manifest.get("rename") or {}).items()}
    render = set(golden.manifest.get("render") or [])
    slug = slugify(project_name)
    out: dict[str, bytes] = {}
    for f in sorted(p for p in golden.tree.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        rel = f.relative_to(golden.tree).as_posix()
        target = renames.get(rel, rel)
        data = f.read_bytes()
        if rel in render:
            data = (data.decode("utf-8").replace("__PROJECT_NAME__", project_name)
                    .replace("__PROJECT_SLUG__", slug)).encode("utf-8")
        out[target] = data
    return out


def tree_digest(golden: Golden) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in golden.tree.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        h.update(f.relative_to(golden.tree).as_posix().encode() + b"\0" + f.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


# --------------------------------------------------------------------------- frozen core
def matches(rel: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(rel, p) for p in patterns)


def read_lock(root: Path) -> dict[str, Any] | None:
    p = root / LOCK
    return (load_yaml(p) or {}) if p.is_file() else None


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _who(root: Path) -> str:
    from .freeze import _who as who
    return who(root)


def _project_files(root: Path, patterns: list[str]) -> list[str]:
    """Files now on disk that fall under a frozen pattern (to catch files *added* to the core)."""
    skip = {".git", ".venv", "node_modules", "__pycache__", ".ekit", ".specify", ".opencode"}
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            rel = (Path(dirpath) / fn).relative_to(root).as_posix()
            if matches(rel, patterns):
                out.append(rel)
    return sorted(out)


@dataclass
class Drift:
    rel: str
    kind: str        # changed | deleted | added | conflict

    def message(self) -> str:
        return {
            "changed": f"{self.rel}: golden core file changed since it was installed or last accepted",
            "deleted": f"{self.rel}: golden core file deleted",
            "added": f"{self.rel}: new file inside the frozen golden core",
            "conflict": f"{self.rel}: unresolved merge conflict from `ekit upgrade` (<<<<<<< / >>>>>>> markers)",
        }[self.kind]


def drift(root: Path) -> list[Drift]:
    lock = read_lock(root)
    if not lock:
        return []
    patterns = list(lock.get("frozen") or [])
    files: dict[str, str] = dict(lock.get("files") or {})
    out: list[Drift] = []
    for rel in sorted(lock.get("conflicts") or []):
        p = root / rel
        if p.is_file() and CONFLICT_RE.search(p.read_text(encoding="utf-8", errors="replace")):
            out.append(Drift(rel, "conflict"))
    conflicted = {d.rel for d in out}
    for rel, sha in sorted(files.items()):
        if not matches(rel, patterns) or rel in conflicted:
            continue
        now = sha_file(root / rel)
        if now is None:
            out.append(Drift(rel, "deleted"))
        elif now != sha:
            out.append(Drift(rel, "changed"))
    for rel in _project_files(root, patterns):
        if rel not in files:
            out.append(Drift(rel, "added"))
    return out


# --------------------------------------------------------------------------- install
def install(project: Any, *, project_name: str | None = None, run_post: bool = True,
            say: Any = print) -> dict[str, Any]:
    golden = for_stack(project.kit, project.stack_id)
    if golden is None:
        raise EkitError(f"The pinned kit has no golden landing zone for stack {project.stack_id}; "
                        "use `/speckit.esdlc.baseline` to generate one.")
    root = project.root
    if read_lock(root):
        raise EkitError(f"{LOCK} already exists: the golden landing zone is installed. "
                        "Kit upgrades bring new revisions (`ekit upgrade`).")
    name = project_name or root.name
    files = materialize(golden, name)
    clashes = [rel for rel, data in files.items()
               if rel != ".gitignore" and (root / rel).is_file() and sha_file(root / rel) != _sha_bytes(data)]
    if clashes:
        raise EkitError("The golden landing zone is for greenfield projects; these files already exist with other "
                        f"content: {', '.join(clashes[:8])}{' …' if len(clashes) > 8 else ''}. Use "
                        "`--baseline generate` (then `/speckit.esdlc.baseline` assesses what is there).")
    installed: dict[str, str] = {}
    for rel, data in files.items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if rel == ".gitignore" and dest.is_file():
            have = dest.read_text(encoding="utf-8").splitlines()
            add = [ln for ln in data.decode("utf-8").splitlines() if ln and ln not in have]
            if add:
                with dest.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(("\n" if have and have[-1].strip() else "") + "\n".join(add) + "\n")
        else:
            dest.write_bytes(data)
        installed[rel] = sha_file(dest) or ""
    lock = {
        "apiVersion": "ekit/v1",
        "kind": "GoldenLock",
        "stack": golden.stack,
        "version": golden.version,
        "tree_sha256": tree_digest(golden),
        "project_name": name,
        "installed_at": _now(),
        "frozen": golden.frozen,
        "files": installed,
        "conflicts": [],
        "history": [{"action": "install", "version": golden.version, "by": _who(root), "at": _now()}],
    }
    dump_yaml(lock, root / LOCK)
    say(f"  golden landing zone {golden.stack} {golden.version}: {len(installed)} file(s) installed, "
        f"core fingerprinted in {LOCK}")
    if run_post:
        for note in post_install(golden, root):
            say(f"  {note}")
    return lock


def post_install(golden: Golden, root: Path) -> list[str]:
    notes = []
    if os.environ.get(SKIP_POST_INSTALL_ENV):
        return [f"post-install steps skipped ({SKIP_POST_INSTALL_ENV} is set): run "
                + "; ".join(" ".join(c) for c in golden.manifest.get("post_install") or [])]
    for argv in golden.manifest.get("post_install") or []:
        exe = shutil.which(str(argv[0]))
        if not exe:
            notes.append(f"!! `{' '.join(argv)}` not run: {argv[0]} is not on PATH. Run it yourself, then `ekit run install`.")
            continue
        proc = subprocess.run([exe, *[str(a) for a in argv[1:]]], cwd=root, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
            notes.append(f"!! `{' '.join(argv)}` failed (exit {proc.returncode}): {' | '.join(tail)}. "
                         "Fix and run it yourself (it needs network access once).")
        else:
            notes.append(f"ran `{' '.join(argv)}`")
    return notes


# --------------------------------------------------------------------------- accept (a person)
def accept(root: Path, reason: str) -> list[str]:
    """Re-fingerprint the golden core after a reviewed change. Returns the files whose record changed."""
    if not reason.strip():
        raise EkitError('A reason is required: ekit baseline accept --reason "..."')
    lock = read_lock(root)
    if not lock:
        raise EkitError(f"No {LOCK}: this project does not use a golden landing zone.")
    found = drift(root)
    unresolved = [d.rel for d in found if d.kind == "conflict"]
    if unresolved:
        raise EkitError(f"Resolve the merge conflict markers first: {', '.join(unresolved)}")
    files = dict(lock.get("files") or {})
    changed = []
    for d in found:
        now = sha_file(root / d.rel)
        if now is None:
            files.pop(d.rel, None)
        else:
            files[d.rel] = now
        changed.append(f"{d.kind}: {d.rel}")
    lock["files"] = files
    lock["conflicts"] = []
    lock.setdefault("history", []).append({"action": "accept", "reason": reason.strip(), "by": _who(root),
                                           "at": _now(), "files": changed})
    dump_yaml(lock, root / LOCK)
    return changed


# --------------------------------------------------------------------------- upgrade (3-way)
def snapshot(golden: Golden | None) -> Path | None:
    """Copy the current golden dir aside before `ekit upgrade` replaces .ekit/kit."""
    if golden is None:
        return None
    tmp = Path(tempfile.mkdtemp(prefix="ekit-golden-old-"))
    shutil.copytree(golden.path, tmp / "golden")
    return tmp / "golden"


def _merge3(ours: bytes, base: bytes, theirs: bytes) -> tuple[bytes, bool]:
    git_exe = shutil.which("git")
    if not git_exe:
        raise EkitError("git is required to merge a new golden revision (`git merge-file`).")
    with tempfile.TemporaryDirectory(prefix="ekit-merge-") as d:
        paths = [Path(d) / n for n in ("ours", "base", "theirs")]
        for p, data in zip(paths, (ours, base, theirs)):
            p.write_bytes(data.replace(b"\r\n", b"\n"))
        proc = subprocess.run([git_exe, "merge-file", "-p", "-L", MERGE_LABELS[0], "-L", MERGE_LABELS[1],
                               "-L", MERGE_LABELS[2], *map(str, paths)], capture_output=True)
        if proc.returncode < 0 or proc.returncode > 127:
            raise EkitError(f"git merge-file failed: {proc.stderr.decode(errors='replace').strip()}")
        return proc.stdout, proc.returncode > 0


def merge_upgrade(root: Path, old_dir: Path | None, new: Golden, say: Any = print) -> dict[str, list[str]]:
    """Apply old golden -> new golden onto the project. Returns {'updated', 'added', 'merged', 'conflicts', 'removed'}."""
    lock = read_lock(root)
    report: dict[str, list[str]] = {k: [] for k in ("updated", "added", "merged", "conflicts", "removed", "kept")}
    if not lock:
        return report
    if lock.get("tree_sha256") == tree_digest(new):
        return report
    name = str(lock.get("project_name") or root.name)
    old = materialize(Golden(old_dir, load_yaml(old_dir / MANIFEST) or {}), name) if old_dir else {}
    new_files = materialize(new, name)
    files = dict(lock.get("files") or {})
    for rel, theirs in sorted(new_files.items()):
        dest = root / rel
        base = old.get(rel)
        if rel == ".gitignore":
            continue                                   # line-merged at install; never replaced
        if not dest.is_file():
            if base is not None:
                report["kept"].append(rel)             # the project deleted it on purpose: leave it deleted
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(theirs)
            files[rel] = sha_file(dest) or ""
            report["added"].append(rel)
            continue
        ours = dest.read_bytes()
        if _sha_bytes(ours) == _sha_bytes(theirs):
            files[rel] = sha_file(dest) or ""
            continue
        if base is not None and _sha_bytes(ours) == _sha_bytes(base):
            dest.write_bytes(theirs)                   # untouched by the project: take the new revision
            files[rel] = sha_file(dest) or ""
            report["updated"].append(rel)
            continue
        merged, conflict = _merge3(ours, base if base is not None else b"", theirs)
        dest.write_bytes(merged)
        if conflict:
            report["conflicts"].append(rel)
        else:
            files[rel] = sha_file(dest) or ""
            report["merged"].append(rel)
    for rel in sorted(set(old) - set(new_files)):
        if (root / rel).is_file():
            report["removed"].append(rel)              # no longer in golden: left in place for a person to decide
    lock.update({"version": new.version, "tree_sha256": tree_digest(new), "frozen": new.frozen, "files": files,
                 "conflicts": sorted(set(lock.get("conflicts") or []) | set(report["conflicts"]))})
    lock.setdefault("history", []).append({"action": "upgrade", "version": new.version, "by": _who(root), "at": _now(),
                                           **{k: v for k, v in report.items() if v}})
    dump_yaml(lock, root / LOCK)
    return report


# --------------------------------------------------------------------------- feature seams
FEATURE_NAME_RE = re.compile(r"^(\d{3})-([a-z0-9][a-z0-9-]*)$")


def feature_package(golden: Golden | None, feature: str) -> str | None:
    """`003-conversation-history` -> `src/app/features/f003_conversation_history` (golden projects)."""
    if golden is None:
        return None
    m = FEATURE_NAME_RE.match(feature)
    if not m:
        raise EkitError(f"'{feature}' is not a feature folder name (NNN-slug).")
    tpl = golden.seams.get("feature_package")
    if not tpl:
        return None
    return tpl.format(number=m.group(1), slug=m.group(2).replace("-", "_"))


def design_feature_package(project: Any, feat: str) -> str | None:
    """0.7.1: `FEAT-02` -> its package. One package per FEAT- (`f002_<prd title slug>`) unless design.yaml groups
    features under a shared `package:` key (`src/app/features/<package>`)."""
    g = for_project(project)
    if g is None:
        return None
    tpl = g.seams.get("feature_package")
    if not tpl:
        return None
    from . import design
    m = re.match(r"^FEAT-(\d{2})$", feat)
    if not m:
        raise EkitError(f"'{feat}' is not a FEAT-nn id.")
    base = tpl.rsplit("/", 1)[0]
    try:
        data = design.load_design(project.root)
    except EkitError:
        data = {}
    spec = (data.get("features") or {}).get(feat)
    if not isinstance(spec, dict):
        raise EkitError(f"{feat} is not under `features` in docs/design/design.yaml.")
    if spec.get("package"):
        return f"{base}/{spec['package']}"
    from .waves import FEAT_HEADING_RE
    slug = "feature"
    req = project.root / "docs" / "requirements"
    for prd in sorted(req.glob("*/prd.md")) if req.is_dir() else []:
        for line in prd.read_text(encoding="utf-8").splitlines():
            h = re.match(rf"^\s*#{{2,4}}\s+\**{feat}\b\**\s*[:\-–—]?\s*(.*?)\**\s*$", line)
            if h and h.group(1).strip():
                slug = re.sub(r"[^a-z0-9]+", "_", h.group(1).lower()).strip("_") or slug
                break
    return tpl.format(number=f"0{m.group(1)}", slug=slug)


def feature_packages(project: Any, feature: str) -> list[str]:
    """0.5.0: the package(s) a feature folder's code lives in. A change request that fixes or extends
    existing features (change.yaml `affects.features`) works in *their* packages; a new feature, or a
    change that affects nothing existing, in its own."""
    g = for_project(project)
    if g is None:
        return []
    from . import changes
    hit = changes.for_feature(project.root, project.root / "specs" / feature)
    if hit and hit[1].get("type") in ("bug", "enhancement"):
        pkgs = [p for f in changes.affected_features(hit[1]) if (p := feature_package(g, f))]
        if pkgs:
            return sorted(set(pkgs))
    own = feature_package(g, feature)
    return [own] if own else []


def feature_test_module(golden: Golden | None, feature: str) -> str | None:
    if golden is None:
        return None
    m = FEATURE_NAME_RE.match(feature)
    tpl = golden.seams.get("acceptance_tests")
    if not m or not tpl:
        return None
    return tpl.format(number=m.group(1), slug=m.group(2).replace("-", "_"))
