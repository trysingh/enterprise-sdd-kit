"""ekit — Enterprise SDD Kit CLI."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from . import __version__, gates, installer, kitsource
from . import questions as oq
from .project import EkitError, Kit, Project, bundled_kit_dir, find_project_root, python_exe
from .runner import run_profile_command


def _interactive(args: argparse.Namespace) -> bool:
    return not getattr(args, "non_interactive", False) and sys.stdin.isatty()


# --------------------------------------------------------------------------- handlers
def cmd_init(args: argparse.Namespace) -> int:
    installer.init(args.target, stack=args.stack, source=args.source, integration=args.integration,
                   force=args.force, interactive=_interactive(args), extra_specify=args.specify_arg or [])
    return 0


def cmd_adopt(args: argparse.Namespace) -> int:
    args.target = "."
    return cmd_init(args)


def cmd_sync(args: argparse.Namespace) -> int:
    installer.sync(Project.load())
    return 0


def cmd_upgrade(args: argparse.Namespace) -> int:
    installer.upgrade(find_project_root(), args.source)
    return 0


def cmd_freeze(args: argparse.Namespace) -> int:
    from . import freeze
    project = Project.load()
    feature = project.resolve_feature(args.feature).name
    rules = freeze.freeze_from_ledger(project.root, feature)
    print(f"{feature} frozen: {len(rules)} deny rule(s) in opencode.json. Restart OpenCode to apply.")
    return 0


def cmd_unfreeze(args: argparse.Namespace) -> int:
    from . import freeze
    project = Project.load()
    feature = project.resolve_feature(args.feature).name
    freeze.unfreeze_feature(project.root, feature, args.reason)
    print(f"{feature} unfrozen (recorded in .ekit/freeze.yaml). Restart OpenCode to apply.\n"
          f"Fix the tests, then run `ekit gate red` while the code is still red: it records new fingerprints and freezes again.")
    return 0


def cmd_stacks(args: argparse.Namespace) -> int:
    src = kitsource.resolve(args.source or "bundled")
    try:
        kit = Kit.load(src.kit_path)
        print(f"Kit {kit.version} (source: {src.kind})")
        for sid, s in kit.stacks.items():
            print(f"  {sid:<20} {', '.join(s.get('profiles', []))}\n  {'':<20} {s.get('description', '')}")
    finally:
        src.cleanup()
    return 0


def require_pinned_cli(project: Project) -> None:
    """With EKIT_REQUIRE_PINNED_CLI=1 (set it in CI), refuse to judge with a CLI other than the pinned one."""
    if os.environ.get(kitsource.STRICT_ENV, "").strip().lower() not in ("1", "true", "yes"):
        return
    pin = kitsource.cli_pin(project.root)
    if not pin.matches:
        raise EkitError(f"{kitsource.STRICT_ENV} is set: {pin.message()}.")


def cmd_gate(args: argparse.Namespace) -> int:
    project = Project.load()
    require_pinned_cli(project)
    ids = gates.gate_ids(project) if args.gate == "all" else [args.gate]
    overall = 0
    for gid in ids:
        res, notes = gates.run_gate(project, gid, feature=args.feature, prd=args.prd)
        out = Path(args.out) if args.out else None
        if out and len(ids) > 1:
            out = out.with_name(f"{out.stem}-{gid}{out.suffix}")
        print(gates.write_report(res, notes, args.format, out, args.verbose))
        if not res.passed:
            overall = 1
    return overall


def cmd_run(args: argparse.Namespace) -> int:
    project = Project.load()
    rc, ran = 0, 0
    for prof in project.profiles:
        if args.profile and args.profile not in prof.id:
            continue
        print(f"==> [{prof.id}] {args.command} (in {project.rel(prof.root) or '.'})", flush=True)
        res = run_profile_command(prof, args.command, stream=True)
        if res is None:
            print("    (not defined for this profile)")
            continue
        ran += 1
        rc = rc or res.returncode
    if ran == 0:
        print(f"No profile defines '{args.command}'.", file=sys.stderr)
        return 2
    return rc


def cmd_context(args: argparse.Namespace) -> int:
    project = Project.load()
    nfrs = project.applicable_nfrs(scope=args.nfr if args.nfr != "all" else None)
    controls: dict[str, list[str]] = {}
    for prof in project.profiles:
        for nid, how in (prof.data.get("controls") or {}).items():
            controls.setdefault(nid, []).append(f"[{prof.id}] {how}")
    data = {
        "stack": project.stack_id,
        "description": project.stack.get("description"),
        "kit_version": project.kit.version,
        "profiles": [
            {"id": p.id, "role": p.role, "root": project.rel(p.root) or ".",
             "runtime": p.data.get("runtime"), "toolchain": p.data.get("toolchain"),
             "layout": p.data.get("layout"), "commands": p.commands, "bdd": p.bdd,
             "agent_rules": p.data.get("agent_rules")}
            for p in project.profiles
        ],
        "nfrs": [
            {**{k: n.get(k) for k in ("id", "title", "scope", "applies_to", "level", "requirement", "verify")},
             "how_in_this_stack": controls.get(n["id"], [])}
            for n in nfrs
        ],
    }
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=110))
    return 0


def cmd_template(args: argparse.Namespace) -> int:
    project = Project.load()
    script = project.root / ".specify" / "scripts" / "python" / "resolve_template.py"
    if script.is_file():
        proc = subprocess.run([python_exe(), str(script), args.name], cwd=project.root,
                              capture_output=True, text=True, encoding="utf-8")
        if proc.returncode == 0 and proc.stdout.strip():
            sys.stdout.write(proc.stdout)
            return 0
    for cand in (project.kit.component("extension") / "templates" / f"{args.name}.md",
                 project.kit.component("preset") / "templates" / f"{args.name}.md"):
        if cand.is_file():
            sys.stdout.write(cand.read_text(encoding="utf-8"))
            return 0
    raise EkitError(f"Template '{args.name}' not found.")


def cmd_questions(args: argparse.Namespace) -> int:
    project = Project.load()
    prd = project.resolve_prd(args.prd)
    if args.action == "list":
        for q in oq.list_questions(prd, args.status):
            flag = "BLOCKING" if q.get("blocking") else "        "
            print(f"{q.get('id')}  {flag}  {q.get('status'):<9} {q.get('owner') or '-':<18} {str(q.get('question')).strip()}")
        return 0
    if args.action == "export":
        out = Path(args.out) if args.out else prd / "questions-for-review.csv"
        n = oq.export_csv(prd, out, only_open=not args.all)
        print(f"Exported {n} question(s) to {project.rel(out.resolve())}. Stakeholders fill `answer` and `answered_by`.")
        return 0
    if args.action == "import":
        if not args.file:
            raise EkitError("questions import needs a CSV file path")
        changed = oq.import_csv(prd, Path(args.file))
        print(f"Updated {len(changed)} question(s): {', '.join(changed) or '-'}")
        print("Next: propagate answers into prd.md, then `ekit gate ready`.")
        return 0
    return 2


def cmd_status(args: argparse.Namespace) -> int:
    project = Project.load()
    lock = kitsource.read_lock(project.root) or {}
    print(f"Project {project.root.name}: stack {project.stack_id}, kit {project.kit.version} "
          f"({kitsource.source_string(lock) if lock else 'unpinned'})")
    pin = kitsource.cli_pin(project.root)
    print(f"ekit CLI {pin.current}, project pins {pin.pinned or 'nothing'}"
          + ("" if pin.matches else f"  !! {pin.message()}"))
    req = project.root / "docs" / "requirements"
    prds = sorted(p for p in req.iterdir() if p.is_dir()) if req.is_dir() else []
    print("\nRequirements")
    if not prds:
        print("  (none yet — /speckit.esdlc.brd)")
    for p in prds:
        line = f"  {p.name:<28}"
        try:
            qs = oq.list_questions(p)
            blocking = sum(1 for q in qs if q.get("blocking") and q.get("status") in ("open", "deferred"))
            line += f" questions open={sum(1 for q in qs if q.get('status') == 'open')} blocking={blocking}"
        except EkitError:
            line += " (no open-questions.yaml)"
        print(line)
    from . import freeze
    frozen = set(freeze.load_state(project.root)["frozen"])
    print("\nFeatures                       spec  scen  plan  red   green frozen")
    for f in project.feature_dirs():
        cells = []
        for gid in ("spec", "scenarios", "plan"):
            try:
                res, _ = gates.run_gate(project, gid, feature=f.name)
                cells.append("ok" if res.passed else "--")
            except EkitError:
                cells.append("--")
        ledger = project.root / ".ekit" / "ledger" / f"{f.name}.yaml"
        phases = {e.get("phase") for e in ((yaml.safe_load(ledger.read_text(encoding="utf-8")) or {}).get("entries") or [])} if ledger.is_file() else set()
        cells += ["ok" if "red" in phases else "--", "ok" if "green" in phases else "--"]
        print(f"  {f.name:<28} " + "    ".join(f"{c:<2}" for c in cells) + f"    {'yes' if f.name in frozen else '--'}")
    if not project.feature_dirs():
        print("  (none yet)")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    try:
        project = Project.load()
    except EkitError:
        project = None
    problems = installer.doctor(project)
    print(f"\n{problems} problem(s)." if problems else "\nAll good.")
    return 1 if problems else 0


# --------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ekit", description="Enterprise SDD Kit for GitHub Spec Kit + OpenCode")
    p.add_argument("--version", action="version", version=f"ekit {__version__} (bundled kit {Kit.load(bundled_kit_dir()).version})")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_init_opts(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--stack", help="stack id (see `ekit stacks`)")
        sp.add_argument("--source", help="kit source: bundled | <path> | git+<url>[@<ref>] (asked if omitted)")
        sp.add_argument("--integration", default=installer.DEFAULT_INTEGRATION, help="Spec Kit integration (default: opencode)")
        sp.add_argument("--force", action="store_true", help="pass --force to `specify init --here` (non-empty dir)")
        sp.add_argument("--non-interactive", action="store_true", help="never prompt (CI); requires --stack")
        sp.add_argument("--specify-arg", action="append", help="extra argument forwarded to `specify init` (repeatable)")

    sp = sub.add_parser("init", help="new project (or `.`): specify init + opencode + kit")
    sp.add_argument("target", help="project directory name, or . for the current directory")
    add_init_opts(sp)
    sp.set_defaults(fn=cmd_init)

    sp = sub.add_parser("adopt", help="existing repository: same as `init .`, brownfield aware")
    add_init_opts(sp)
    sp.set_defaults(fn=cmd_adopt)

    sp = sub.add_parser("sync", help="re-apply the pinned kit (extension, preset, AGENTS.md, agents)")
    sp.set_defaults(fn=cmd_sync)

    sp = sub.add_parser("upgrade", help="re-fetch the kit (same or new --source), re-pin and sync")
    sp.add_argument("--source")
    sp.set_defaults(fn=cmd_upgrade)

    sp = sub.add_parser("freeze", help="re-apply the edit protection for a red feature (done automatically by `gate red`)")
    sp.add_argument("feature", nargs="?", help="feature folder, e.g. 001-user-admin (default: the current one)")
    sp.set_defaults(fn=cmd_freeze)

    sp = sub.add_parser("unfreeze", help="lift the edit protection of a feature's red tests (needs a reason; audited)")
    sp.add_argument("feature", nargs="?", help="feature folder, e.g. 001-user-admin (default: the current one)")
    sp.add_argument("--reason", required=True, help="why the red tests must change; stored in .ekit/freeze.yaml")
    sp.set_defaults(fn=cmd_unfreeze)

    sp = sub.add_parser("stacks", help="list stacks offered by a kit source")
    sp.add_argument("--source")
    sp.set_defaults(fn=cmd_stacks)

    sp = sub.add_parser("gate", help="run a gate: intake | ready | spec | scenarios | plan | baseline | red | red-recorded | green | all")
    sp.add_argument("gate")
    sp.add_argument("--feature", help="feature dir name under specs/ (default: branch / SPECIFY_FEATURE)")
    sp.add_argument("--prd", help="docs/requirements/<slug>")
    sp.add_argument("--format", choices=["text", "json", "junit"], default="text")
    sp.add_argument("--out", help="also write the report to this file")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(fn=cmd_gate)

    sp = sub.add_parser("run", help="run a profile command: install | lint | format | typecheck | unit | acceptance | coverage | sca")
    sp.add_argument("command")
    sp.add_argument("--profile", help="only profiles whose id contains this text, e.g. backend")
    sp.set_defaults(fn=cmd_run)

    sp = sub.add_parser("context", help="print stack, profiles and applicable NFRs (for agents)")
    sp.add_argument("--nfr", choices=["all", "feature", "platform"], default="all")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_context)

    sp = sub.add_parser("template", help="print a resolved Spec Kit template by name")
    sp.add_argument("name")
    sp.set_defaults(fn=cmd_template)

    sp = sub.add_parser("questions", help="open questions: list | export | import")
    sp.add_argument("action", choices=["list", "export", "import"])
    sp.add_argument("file", nargs="?", help="CSV file for import")
    sp.add_argument("--prd")
    sp.add_argument("--status", help="filter for list (open, answered, …)")
    sp.add_argument("--out", help="CSV path for export")
    sp.add_argument("--all", action="store_true", help="export answered questions too")
    sp.set_defaults(fn=cmd_questions)

    sp = sub.add_parser("status", help="pipeline status for all PRDs and features")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("doctor", help="check tools, kit integrity and installation")
    sp.set_defaults(fn=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
        except (ValueError, OSError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except EkitError as exc:
        print(f"ekit: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nekit: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
