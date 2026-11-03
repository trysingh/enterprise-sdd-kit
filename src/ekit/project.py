"""Project model: locate the project, load the pinned kit, resolve stack/profiles/NFRs/feature."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

EKIT_DIR = ".ekit"
PROJECT_FILE = "project.yaml"
LOCK_FILE = "kit.lock.yaml"
KIT_DIR = "kit"
FEATURE_DIR_RE = re.compile(r"^(\d{3})-[a-z0-9][a-z0-9-]*$")


class EkitError(Exception):
    """User-facing error: printed without a traceback."""


def load_yaml(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except FileNotFoundError:
        raise EkitError(f"File not found: {path}") from None
    except yaml.YAMLError as exc:
        raise EkitError(f"Invalid YAML in {path}: {exc}") from None


def dump_yaml(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)


def bundled_kit_dir() -> Path:
    return Path(__file__).resolve().parent / "kit"


def find_project_root(start: Path | None = None) -> Path:
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / EKIT_DIR / PROJECT_FILE).is_file():
            return candidate
    raise EkitError(
        "Not inside an ekit project (no .ekit/project.yaml found). Run `ekit init` or `ekit adopt` first."
    )


def git(root: Path, *args: str) -> str | None:
    exe = shutil.which("git")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, *args], cwd=root, capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return None


@dataclass
class Profile:
    id: str
    role: str
    root: Path
    data: dict[str, Any]

    @property
    def commands(self) -> dict[str, Any]:
        return self.data.get("commands") or {}

    @property
    def bdd(self) -> dict[str, Any]:
        return self.data.get("bdd") or {}

    @property
    def runs_bdd(self) -> bool:
        fw = self.bdd.get("framework")
        return bool(fw) and fw != "inherit" and "acceptance" in self.commands


@dataclass
class Kit:
    path: Path
    manifest: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "Kit":
        manifest_path = path / "kit.yaml"
        if not manifest_path.is_file():
            raise EkitError(f"No kit.yaml in {path}; not a valid kit source.")
        return cls(path=path, manifest=load_yaml(manifest_path))

    @property
    def version(self) -> str:
        return str(self.manifest.get("metadata", {}).get("version", "0.0.0"))

    @property
    def stacks(self) -> dict[str, Any]:
        return self.manifest.get("stacks") or {}

    def component(self, name: str) -> Path:
        rel = (self.manifest.get("components") or {}).get(name)
        if not rel:
            raise EkitError(f"Kit manifest has no component '{name}'.")
        return self.path / rel

    def profile_data(self, profile_id: str) -> dict[str, Any]:
        p = self.path / "profiles" / profile_id / "profile.yaml"
        if not p.is_file():
            raise EkitError(f"Profile '{profile_id}' not found in kit ({p}).")
        return load_yaml(p)

    def nfr_catalog(self) -> dict[str, Any]:
        return load_yaml(self.component("nfr_catalog"))

    def policy(self) -> dict[str, Any]:
        return load_yaml(self.component("policy"))


@dataclass
class Project:
    root: Path
    config: dict[str, Any]
    kit: Kit
    _profiles: list[Profile] | None = field(default=None, repr=False)

    @classmethod
    def load(cls, start: Path | None = None) -> "Project":
        root = find_project_root(start)
        config = load_yaml(root / EKIT_DIR / PROJECT_FILE) or {}
        kit = Kit.load(root / EKIT_DIR / KIT_DIR)
        return cls(root=root, config=config, kit=kit)

    # ---------------------------------------------------------------- stack
    @property
    def stack_id(self) -> str:
        sid = self.config.get("stack")
        if sid not in self.kit.stacks:
            raise EkitError(
                f"Stack '{sid}' from .ekit/project.yaml is not defined in the pinned kit "
                f"(available: {', '.join(self.kit.stacks)})."
            )
        return sid

    @property
    def stack(self) -> dict[str, Any]:
        return self.kit.stacks[self.stack_id]

    @property
    def profiles(self) -> list[Profile]:
        if self._profiles is None:
            roots = self.stack.get("roots") or {}
            result = []
            for pid in self.stack.get("profiles", []):
                data = self.kit.profile_data(pid)
                role = data.get("metadata", {}).get("role", pid.split("/")[0])
                result.append(Profile(pid, role, (self.root / roots.get(role, ".")).resolve(), data))
            self._profiles = result
        return self._profiles

    @property
    def roles(self) -> set[str]:
        return {p.role for p in self.profiles}

    def applicable_nfrs(self, scope: str | None = None) -> list[dict[str, Any]]:
        roles = self.roles
        out = []
        for n in self.kit.nfr_catalog().get("nfrs", []):
            applies = n.get("applies_to", "all")
            if applies != "all" and applies not in roles:
                continue
            if scope and n.get("scope") != scope:
                continue
            out.append(n)
        return out

    # ---------------------------------------------------------------- features / PRDs
    def feature_dirs(self) -> list[Path]:
        specs = self.root / "specs"
        if not specs.is_dir():
            return []
        return sorted(p for p in specs.iterdir() if p.is_dir() and FEATURE_DIR_RE.match(p.name))

    def resolve_feature(self, explicit: str | None) -> Path:
        if explicit:
            cand = Path(explicit)
            if not cand.is_absolute():
                cand = self.root / "specs" / explicit if not (self.root / explicit).is_dir() else self.root / explicit
            if not cand.is_dir():
                raise EkitError(f"Feature directory not found: {explicit}")
            return cand.resolve()
        env = os.environ.get("SPECIFY_FEATURE")
        if env and (self.root / "specs" / env).is_dir():
            return (self.root / "specs" / env).resolve()
        branch = git(self.root, "rev-parse", "--abbrev-ref", "HEAD")
        if branch and FEATURE_DIR_RE.match(branch) and (self.root / "specs" / branch).is_dir():
            return (self.root / "specs" / branch).resolve()
        candidates = [p for p in self.feature_dirs() if not p.name.startswith("000-")]
        if len(candidates) == 1:
            return candidates[0].resolve()
        raise EkitError(
            "Cannot tell which feature to check. Pass --feature <NNN-name>, set SPECIFY_FEATURE, "
            "or check out the feature branch."
        )

    def resolve_prd(self, explicit: str | None, feature_dir: Path | None = None) -> Path:
        if explicit:
            cand = Path(explicit)
            if not cand.is_absolute():
                cand = self.root / explicit
            if not cand.is_dir():
                alt = self.root / "docs" / "requirements" / explicit
                if alt.is_dir():
                    cand = alt
            if not cand.is_dir():
                raise EkitError(f"PRD folder not found: {explicit}")
            return cand.resolve()
        if feature_dir and (feature_dir / "trace.yaml").is_file():
            trace = load_yaml(feature_dir / "trace.yaml") or {}
            if trace.get("prd"):
                return (self.root / trace["prd"]).resolve()
        req = self.root / "docs" / "requirements"
        folders = sorted(p for p in req.iterdir() if p.is_dir()) if req.is_dir() else []
        if len(folders) == 1:
            return folders[0].resolve()
        raise EkitError("Cannot tell which PRD to check. Pass --prd docs/requirements/<slug>.")

    def rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(path)


def python_exe() -> str:
    return sys.executable or "python"
