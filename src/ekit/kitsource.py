"""Kit distribution: choose where the kit comes from at runtime, vendor it, and pin it.

Sources
  bundled                  the kit shipped inside this ekit installation (offline, simplest)
  <path>                   a local folder (e.g. a clone of your organisation's kit repo)
  git+<url>[@<ref>]        any git remote (GitHub, GitLab, Azure Repos, Bitbucket, internal)

Whatever the source, the kit is copied into <project>/.ekit/kit and pinned in
.ekit/kit.lock.yaml (source, ref, commit, version, sha256 of the content), so every
developer and every CI run uses byte-identical rules until someone runs `ekit upgrade`.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .project import EKIT_DIR, KIT_DIR, LOCK_FILE, EkitError, Kit, bundled_kit_dir, dump_yaml, load_yaml

KIT_LOCATIONS = [".", "kit", "src/ekit/kit"]   # where kit.yaml may live inside a source


@dataclass
class ResolvedSource:
    kind: str          # bundled | path | git
    location: str
    ref: str | None
    commit: str | None
    kit_path: Path
    _tmp: tempfile.TemporaryDirectory | None = None

    def cleanup(self) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()


def _find_kit(base: Path) -> Path:
    for rel in KIT_LOCATIONS:
        if (base / rel / "kit.yaml").is_file():
            return (base / rel).resolve()
    raise EkitError(f"No kit.yaml found in {base} (looked in {', '.join(KIT_LOCATIONS)}).")


def resolve(source: str) -> ResolvedSource:
    source = source.strip()
    if source in ("", "bundled"):
        return ResolvedSource("bundled", "bundled", None, None, bundled_kit_dir())
    if source.startswith("git+"):
        url, ref = source[4:], None
        # split an @ref suffix without breaking ssh urls like git@host:org/repo.git
        head, sep, tail = url.rpartition("@")
        if sep and head and "/" not in tail and ":" not in tail:
            url, ref = head, tail
        git_exe = shutil.which("git")
        if not git_exe:
            raise EkitError("git is required for git+ kit sources.")
        tmp = tempfile.TemporaryDirectory(prefix="ekit-kit-")
        dest = Path(tmp.name) / "src"
        cmd = [git_exe, "clone", "--depth", "1", "--quiet"]
        if ref:
            cmd += ["--branch", ref]
        cmd += [url, str(dest)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tmp.cleanup()
            raise EkitError(f"git clone failed for {url}{'@' + ref if ref else ''}:\n{proc.stderr.strip()}")
        commit = subprocess.run([git_exe, "rev-parse", "HEAD"], cwd=dest, capture_output=True, text=True).stdout.strip()
        return ResolvedSource("git", url, ref, commit or None, _find_kit(dest), tmp)
    p = Path(source).expanduser()
    if not p.exists():
        raise EkitError(f"Kit source path does not exist: {p}")
    return ResolvedSource("path", str(p.resolve()), None, None, _find_kit(p))


def digest(kit_path: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in kit_path.rglob("*") if p.is_file() and "__pycache__" not in p.parts and ".git" not in p.parts):
        h.update(f.relative_to(kit_path).as_posix().encode())
        h.update(b"\0")
        # normalise line endings so Windows checkouts (core.autocrlf) hash the same
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    return h.hexdigest()


def vendor(project_root: Path, src: ResolvedSource) -> dict:
    kit = Kit.load(src.kit_path)
    target = project_root / EKIT_DIR / KIT_DIR
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(src.kit_path, target, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    lock = {
        "apiVersion": "ekit/v1",
        "kind": "KitLock",
        "source": {"kind": src.kind, "location": src.location, "ref": src.ref, "commit": src.commit},
        "kit": {"name": kit.manifest.get("metadata", {}).get("name"), "version": kit.version},
        "sha256": digest(target),
        "vendored_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
    }
    dump_yaml(lock, project_root / EKIT_DIR / LOCK_FILE)
    return lock


def read_lock(project_root: Path) -> dict | None:
    p = project_root / EKIT_DIR / LOCK_FILE
    return load_yaml(p) if p.is_file() else None


def source_string(lock: dict) -> str:
    s = lock.get("source") or {}
    if s.get("kind") == "git":
        return f"git+{s['location']}" + (f"@{s['ref']}" if s.get("ref") else "")
    return s.get("location") or "bundled"
