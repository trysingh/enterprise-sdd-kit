"""init / adopt / sync / upgrade: one command instead of the manual specify + opencode steps."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from . import kitsource
from .project import EKIT_DIR, PROJECT_FILE, EkitError, Project, dump_yaml, load_yaml

BLOCK_BEGIN = "<!-- ekit:begin"
BLOCK_END = "<!-- ekit:end -->"
DEFAULT_INTEGRATION = "opencode"


def say(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------- specify CLI
def specify_argv() -> list[str]:
    override = os.environ.get("EKIT_SPECIFY")
    if override:
        return shlex.split(override, posix=(os.name != "nt"))
    exe = shutil.which("specify")
    if not exe:
        raise EkitError(
            "Spec Kit CLI `specify` not found on PATH. Install it with `uv tool install specify-cli` "
            "(or set EKIT_SPECIFY to its path)."
        )
    return [exe]


def run_specify(args: list[str], cwd: Path) -> None:
    argv = specify_argv() + args
    say(f"  $ specify {' '.join(args)}")
    proc = subprocess.run(argv, cwd=cwd)
    if proc.returncode != 0:
        raise EkitError(f"`specify {' '.join(args)}` failed with exit code {proc.returncode}.")


def installed_integrations(root: Path) -> list[str]:
    p = root / ".specify" / "integration.json"
    if not p.is_file():
        return []
    try:
        return list(json.loads(p.read_text(encoding="utf-8")).get("installed_integrations") or [])
    except json.JSONDecodeError:
        return []


# --------------------------------------------------------------------------- prompts
def ask_choice(question: str, options: list[tuple[str, str]], default: int = 0) -> str:
    say(question)
    for i, (key, label) in enumerate(options, 1):
        say(f"  {i}) {key:<20} {label}")
    while True:
        raw = input(f"Choose [1-{len(options)}] (default {default + 1}): ").strip()
        if not raw:
            return options[default][0]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        say("  Please enter a number from the list.")


def choose_source(given: str | None, interactive: bool) -> str:
    if given:
        return given
    env = os.environ.get("EKIT_KIT_SOURCE")
    if env:
        return env
    if not interactive:
        return "bundled"
    pick = ask_choice(
        "Where should the engineering kit come from?",
        [("bundled", "kit shipped with this ekit install (offline)"),
         ("local folder", "a folder on this machine, e.g. a clone of your org's kit repo"),
         ("git repository", "a git URL, optionally pinned to a tag or branch")],
    )
    if pick == "bundled":
        return "bundled"
    if pick == "local folder":
        return input("Path to the kit folder: ").strip()
    url = input("Git URL (https or ssh): ").strip()
    ref = input("Tag/branch (empty = default branch): ").strip()
    return f"git+{url}" + (f"@{ref}" if ref else "")


def choose_stack(given: str | None, stacks: dict, interactive: bool) -> str:
    if given:
        if given not in stacks:
            raise EkitError(f"Unknown stack '{given}'. Available: {', '.join(stacks)}")
        return given
    if not interactive:
        raise EkitError(f"--stack is required in non-interactive mode. Available: {', '.join(stacks)}")
    return ask_choice("Which stack is this project?", [(k, v.get("description", "")) for k, v in stacks.items()])


# --------------------------------------------------------------------------- opencode wiring
def render_agents_block(project: Project) -> str:
    tpl = (project.kit.component("opencode") / "AGENTS.block.md").read_text(encoding="utf-8")
    rules = []
    for prof in project.profiles:
        r = (prof.data.get("agent_rules") or "").strip()
        if r:
            rules.append(f"### {prof.id} (code root: `{project.rel(prof.root) or '.'}`)\n\n{r}")
    return (tpl.replace("{stack}", f"{project.stack_id} — {project.stack.get('description', '')}")
               .replace("{profiles}", ", ".join(p.id for p in project.profiles))
               .replace("{agent_rules}", "\n\n".join(rules)))


def write_agents_md(project: Project) -> None:
    path = project.root / "AGENTS.md"
    block = render_agents_block(project).rstrip() + "\n"
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if BLOCK_BEGIN in text and BLOCK_END in text:
            text = re.sub(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END) + r"\n?", lambda _: block, text, flags=re.S)
        else:
            text = block + "\n" + text
    else:
        text = block
    path.write_text(text, encoding="utf-8", newline="\n")


def install_opencode_assets(project: Project) -> None:
    src = project.kit.component("opencode") / "agents"
    dest = project.root / ".opencode" / "agents"
    dest.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("*.md")):
        shutil.copy2(f, dest / f.name)
    write_agents_md(project)


# --------------------------------------------------------------------------- scaffolding
OVERRIDES_SAMPLE = """\
# Project-level relaxations of the kit gate policy. Reviewed in pull requests.
# Every entry needs `reason`, `approved_by` and `expires` (YYYY-MM-DD); otherwise it is ignored
# and the gate report says why. Expired entries stop applying by themselves.
#
# overrides:
#   GREEN-SCA:
#     severity: warn            # error -> warn
#     reason: "Vendor fix for CVE-XXXX pending; tracked in JIRA-123"
#     approved_by: "Security Architect"
#     expires: 2026-12-31
#   BASE-LINT:
#     enabled: false
#     reason: "Brownfield: lint debt tracked in ADR-0004"
#     approved_by: "Tech Lead"
#     expires: 2026-12-31
overrides: {}
"""

GITIGNORE_LINES = ["reports/", "target/cucumber-reports/", ".ekit/tmp/"]


def scaffold(project: Project) -> None:
    for d in ("docs/requirements", "docs/engineering", "docs/adr", ".ekit/ledger", "specs"):
        (project.root / d).mkdir(parents=True, exist_ok=True)
        keep = project.root / d / ".gitkeep"
        if not any((project.root / d).iterdir()):
            keep.touch()
    ov = project.root / ".ekit" / "policy.overrides.yaml"
    if not ov.exists():
        ov.write_text(OVERRIDES_SAMPLE, encoding="utf-8", newline="\n")
    gi = project.root / ".gitignore"
    existing = gi.read_text(encoding="utf-8").splitlines() if gi.is_file() else []
    wanted = list(GITIGNORE_LINES)
    for prof in project.profiles:  # ENV-01: environment folders (.venv/, node_modules/, target/ …)
        for line in (prof.data.get("environment") or {}).get("gitignore", []) or []:
            if line not in wanted:
                wanted.append(line)
    missing = [ln for ln in wanted if ln not in existing]
    if missing:
        with gi.open("a", encoding="utf-8", newline="\n") as fh:
            if existing and existing[-1].strip():
                fh.write("\n")
            fh.write("# ekit\n" + "\n".join(missing) + "\n")


def install_speckit_components(project: Project) -> None:
    ext = project.kit.component("extension")
    preset = project.kit.component("preset")
    run_specify(["extension", "add", str(ext), "--dev", "--force"], project.root)
    # preset priority 5 so it wins over community presets installed later at the default 10
    run_specify(["preset", "add", "--dev", str(preset), "--priority", "5"], project.root)
    seed_constitution(project)


def seed_constitution(project: Project) -> None:
    """`specify init` copies the *core* constitution template into .specify/memory before our
    preset exists. If that file is still the untouched placeholder version, replace it with the
    enterprise template so /speckit.constitution starts from principles I-VIII. A constitution
    that has already been ratified (no placeholders left) is never touched."""
    mem = project.root / ".specify" / "memory" / "constitution.md"
    tpl = project.kit.component("preset") / "templates" / "constitution-template.md"
    if not tpl.is_file():
        return
    if mem.is_file() and "[PRINCIPLE_1_NAME]" not in mem.read_text(encoding="utf-8"):
        return
    mem.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(tpl, mem)
    say("  seeded .specify/memory/constitution.md with the enterprise constitution template")


def write_project_file(root: Path, stack: str, mode: str, integration: str) -> None:
    path = root / EKIT_DIR / PROJECT_FILE
    data = load_yaml(path) if path.is_file() else {}
    data = data or {}
    data.update({
        "apiVersion": "ekit/v1",
        "kind": "EkitProject",
        "stack": stack,
        "mode": data.get("mode", mode),
        "integration": integration,
    })
    data.setdefault("created", dt.date.today().isoformat())
    dump_yaml(data, path)


# --------------------------------------------------------------------------- commands
def init(target: str, *, stack: str | None, source: str | None, integration: str,
         force: bool, interactive: bool, extra_specify: list[str]) -> Path:
    here = target in (".", "")
    root = Path.cwd() if here else Path(target).resolve()
    src = kitsource.resolve(choose_source(source, interactive))
    try:
        stacks = kitsource.Kit.load(src.kit_path).stacks
        stack = choose_stack(stack, stacks, interactive)

        has_code = root.is_dir() and any(
            p.name not in (".git", ".specify", ".opencode", ".ekit", ".gitignore", "README.md")
            for p in root.iterdir()
        )
        mode = "brownfield" if has_code else "greenfield"
        say(f"\n==> Spec Kit ({mode})")
        script_flag = ["--script", "py"]           # Python scripts: identical on Windows and POSIX
        ni = [] if interactive else ["--non-interactive"]
        if (root / ".specify").is_dir():
            say("  .specify/ exists; keeping it")
        elif here or root.exists():
            root.mkdir(parents=True, exist_ok=True)
            run_specify(["init", "--here", "--integration", integration, *script_flag, *ni,
                         *(["--force"] if force else []), *extra_specify], root)
        else:
            run_specify(["init", str(root), "--integration", integration, *script_flag, *ni, *extra_specify],
                        root.parent)
        if integration not in installed_integrations(root):
            run_specify(["integration", "install", integration, *script_flag], root)

        say("\n==> Vendoring engineering kit")
        lock = kitsource.vendor(root, src)
        say(f"  kit {lock['kit']['version']} from {kitsource.source_string(lock)} -> .ekit/kit (sha256 {lock['sha256'][:12]}…)")
        write_project_file(root, stack, mode, integration)
    finally:
        src.cleanup()

    project = Project.load(root)
    say("\n==> Installing Spec Kit extension + preset")
    install_speckit_components(project)
    say("\n==> OpenCode rules and agents")
    install_opencode_assets(project)
    scaffold(project)
    apply_edit_protection(project)
    next_steps(project)
    return root


def sync(project: Project) -> None:
    say("==> Re-applying kit to Spec Kit and OpenCode")
    if _preset_installed(project):
        run_specify(["preset", "remove", "enterprise-baseline"], project.root)
    install_speckit_components(project)
    install_opencode_assets(project)
    scaffold(project)
    apply_edit_protection(project)


def apply_edit_protection(project: Project) -> None:
    from . import freeze
    try:
        rules = freeze.sync_permissions(project.root)
        say(f"  opencode.json: {len(rules)} deny rule(s) protect ekit/OpenCode wiring and frozen tests from agent edits")
    except EkitError as exc:
        say(f"  !! edit protection not applied: {exc}")


def _preset_installed(project: Project) -> bool:
    return (project.root / ".specify" / "presets" / "enterprise-baseline").is_dir()


def upgrade(root: Path, source: str | None) -> None:
    """Works from the project root only, so it can also repair a missing or edited .ekit/kit."""
    lock = kitsource.read_lock(root) or {}
    src_str = source or (kitsource.source_string(lock) if lock else "bundled")
    old = (lock.get("kit") or {}).get("version")
    src = kitsource.resolve(src_str)
    try:
        new_lock = kitsource.vendor(root, src)
    finally:
        src.cleanup()
    old_cli = (lock.get("ekit") or {}).get("version") or "not recorded"
    say(f"Kit {old} -> {new_lock['kit']['version']} from {kitsource.source_string(new_lock)}")
    say(f"ekit CLI pin {old_cli} -> {new_lock['ekit']['version']}: everyone, and CI, must now run this CLI version")
    if new_lock["source"]["kind"] == "bundled":
        say("  note: source 'bundled' means the kit shipped inside the CLI you are running now, "
            "so the CLI version also decides the kit version")
    sync(Project.load(root))


def next_steps(project: Project) -> None:
    say(f"""
Done. Stack: {project.stack_id} ({', '.join(p.id for p in project.profiles)})

Next, inside `opencode` in {project.root}:
  1. /speckit.constitution          ratify the enterprise constitution for this project
  2. /speckit.esdlc.baseline        build (greenfield) or assess (brownfield) the landing zone
  3. /speckit.esdlc.brd <brd file>  BRD -> PRD + open questions
  4. /speckit.esdlc.questions       resolve blocking questions (or `ekit questions export`)
  5. /speckit.specify FEAT-01 -> /speckit.esdlc.gherkin -> /speckit.plan -> /speckit.tasks
     -> /speckit.esdlc.red -> /speckit.implement

Check state any time with `ekit status`; gates run with `ekit gate <id>`.""")


def doctor(project: Project | None) -> int:
    problems = 0

    def row(ok: bool, label: str, detail: str = "") -> None:
        nonlocal problems
        problems += 0 if ok else 1
        say(f"  [{'ok' if ok else '!!'}] {label}" + (f" — {detail}" if detail else ""))

    say("Tools")
    row(sys.version_info >= (3, 11), "python >= 3.11", sys.version.split()[0])
    for tool, hint in [("git", "required"), ("uv", "used by Spec Kit and Python stacks")]:
        row(bool(shutil.which(tool)), tool, shutil.which(tool) or hint)
    try:
        row(True, "specify", " ".join(specify_argv()))
    except EkitError as exc:
        row(False, "specify", str(exc))
    row(bool(shutil.which("opencode")), "opencode", shutil.which("opencode") or "npm i -g opencode-ai")
    if project is None:
        return problems
    say(f"\nProject {project.root}")
    lock = kitsource.read_lock(project.root)
    if lock:
        actual = kitsource.digest(project.root / ".ekit" / "kit")
        row(actual == lock.get("sha256"), "kit integrity",
            "matches lock" if actual == lock.get("sha256") else "kit files changed since vendoring; run `ekit upgrade` or revert")
        pin = kitsource.cli_pin(project.root)
        row(pin.matches, "ekit CLI matches the project pin",
            f"ekit {pin.current}" if pin.matches else pin.message())
    else:
        row(False, "kit lock", "missing .ekit/kit.lock.yaml")
    row(DEFAULT_INTEGRATION in installed_integrations(project.root), "opencode integration")
    row((project.root / ".specify" / "extensions" / "esdlc").is_dir(), "esdlc extension")
    row(_preset_installed(project), "enterprise-baseline preset")
    say("\nEdit protection (opencode.json)")
    from . import freeze
    for ok, label, detail in freeze.verify(project.root):
        row(ok, label, detail)
    say(f"\nEnvironments (ENV-01)")
    from .checks import venv_python_version  # local import keeps installer light
    for prof in project.profiles:
        env = prof.data.get("environment")
        if not env:
            continue
        pin = prof.root / env["pin_file"] if env.get("pin_file") else None
        row(pin is None or pin.is_file(), f"{prof.id} pin {env.get('pin_file')}",
            (pin.read_text(encoding="utf-8").strip() if pin and pin.is_file() else "missing (created by the landing zone)"))
        if env.get("dir"):
            d = prof.root / env["dir"]
            detail = "present" if d.is_dir() else "not created yet: `ekit run install`"
            if env.get("kind") == "python-venv" and d.is_dir():
                detail = f"present, Python {venv_python_version(d) or '?'}"
            row(True, f"{prof.id} {project.rel(d)}/", detail)

    say(f"\nStack {project.stack_id}")
    needs = set()
    for prof in project.profiles:
        for spec in prof.commands.values():
            argv = spec.get("run") if isinstance(spec, dict) else spec
            if argv:
                needs.add(str(argv[0]))
    for exe in sorted(needs):
        if exe == "{mvnw}":
            has = any((p.root / ("mvnw.cmd" if os.name == "nt" else "mvnw")).is_file() for p in project.profiles) or shutil.which("mvn")
            row(bool(has), "maven wrapper / mvn", "created by the landing zone" if not has else "")
            row(bool(shutil.which("java")), "java", shutil.which("java") or "JDK 21 required")
        else:
            row(bool(shutil.which(exe)), exe, shutil.which(exe) or "not on PATH")
    return problems
