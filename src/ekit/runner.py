"""Cross-platform execution of profile commands (argv lists, no shell)."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .project import EkitError, Profile


@dataclass
class RunResult:
    profile: str
    command: str
    argv: list[str]
    cwd: Path
    returncode: int
    output: str


def _resolve_placeholder(token: str, cwd: Path) -> str:
    if token == "{mvnw}":
        if os.name == "nt":
            cand = cwd / "mvnw.cmd"
        else:
            cand = cwd / "mvnw"
        if cand.is_file():
            return str(cand)
        mvn = shutil.which("mvn")
        if mvn:
            return mvn
        raise EkitError(f"Neither Maven wrapper ({cand.name}) in {cwd} nor `mvn` on PATH.")
    if token == "{gradlew}":
        cand = cwd / ("gradlew.bat" if os.name == "nt" else "gradlew")
        if cand.is_file():
            return str(cand)
        gradle = shutil.which("gradle")
        if gradle:
            return gradle
        raise EkitError(f"Neither Gradle wrapper nor `gradle` on PATH (cwd {cwd}).")
    return token


def build_argv(spec: Any, cwd: Path) -> list[str]:
    if isinstance(spec, dict):
        spec = spec.get("run")
    if isinstance(spec, str):
        raise EkitError(f"Profile command must be an argv list, got string: {spec!r}")
    if not spec:
        raise EkitError("Empty profile command.")
    argv = [_resolve_placeholder(str(t), cwd) for t in spec]
    exe = argv[0]
    # Resolve executables via PATH (handles npm.cmd / uv.exe on Windows).
    if not os.path.isabs(exe):
        found = shutil.which(exe, path=os.environ.get("PATH"))
        if not found:
            raise EkitError(f"Executable `{exe}` not found on PATH (needed in {cwd}).")
        argv[0] = found
    return argv


def command_cwd(spec: Any, profile: Profile) -> Path:
    if isinstance(spec, dict) and spec.get("cwd"):
        return (profile.root / spec["cwd"]).resolve()
    return profile.root


def run_profile_command(
    profile: Profile, name: str, *, stream: bool = False, timeout: int | None = None
) -> RunResult | None:
    spec = profile.commands.get(name)
    if spec is None:
        return None
    cwd = command_cwd(spec, profile)
    if not cwd.is_dir():
        raise EkitError(f"Working directory for {profile.id}:{name} does not exist: {cwd}")
    argv = build_argv(spec, cwd)
    if stream:
        proc = subprocess.run(argv, cwd=cwd, timeout=timeout)
        return RunResult(profile.id, name, argv, cwd, proc.returncode, "")
    proc = subprocess.run(
        argv, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
    )
    return RunResult(profile.id, name, argv, cwd, proc.returncode, (proc.stdout or "") + (proc.stderr or ""))
