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


def cmd_fix_red(args: argparse.Namespace) -> int:
    from . import fixred
    project = Project.load()
    require_pinned_cli(project)
    feature = project.resolve_feature(args.feature).name
    clean, report = fixred.fix_red(project, feature, args.reason)
    print(report)
    if not clean:
        print(f"\n{feature}: still not a clean red (see above) — production source has been restored either way. "
              f"Fix the test further and run `ekit fix-red {feature} --reason \"...\"` again.")
        return 1
    print(f"\n{feature}: clean red, re-frozen, production source restored. Review the test diff, then:\n"
          f"  git add -A && git commit -m \"test({feature.split('-', 1)[0]}): red (...)\"\n"
          f"then `ekit gate green --feature {feature}`.")
    return 0


def cmd_unfreeze(args: argparse.Namespace) -> int:
    from . import freeze
    project = Project.load()
    feature = project.resolve_feature(args.feature).name
    narrow = None if args.allow_src else freeze.source_patterns(project)
    freeze.unfreeze_feature(project.root, feature, args.reason, narrow_src=narrow)
    print(f"{feature} unfrozen (recorded in .ekit/freeze.yaml). Restart OpenCode to apply.")
    if narrow:
        print(f"Production source is also denied until this re-freezes: {', '.join(narrow)}. "
              "The point of unfreezing is to fix the test, not to implement; pass --allow-src to skip this.")
    print("Fix the tests, then run `ekit gate red` while the code is still red: it records new fingerprints and freezes again.")
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
    from . import models, waves
    plan = project.wave_plan
    print(f"Waves: {waves.project_mode(project.root)}" + (f", current {plan.current} of {', '.join(plan.ids)}" if plan else "")
          + (f"; inactive: {', '.join(p.id for p in project.inactive_profiles)}" if plan and project.inactive_profiles else ""))
    rts, _ = models.routes(project.root, project.kit)
    if rts:
        tiers = ((models.load_config(project.root) or {}).get("tiers") or {})
        print("Model routing: " + ", ".join(f"{t}={(tiers.get(t) or {}).get('model') or 'default'}" for t in ("flagship", "standard", "light")))
    else:
        print("Model routing: off")
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
    from . import landing
    lz_state, lz_detail = landing.status(project)
    print(f"\nLanding zone\n  baseline: {lz_state} — {lz_detail}")
    smoke = landing.smoke_summary(project)
    if smoke:
        print(f"  {smoke}")
    print("\nFeatures                       spec  scen  plan  red   green frozen")
    features = [f for f in project.feature_dirs() if not f.name.startswith("000-")]
    for f in features:
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
    if not features:
        print("  (none yet)")
    return 0


def cmd_wave(args: argparse.Namespace) -> int:
    from . import waves
    project = Project.load()
    root, kit = project.root, project.kit
    a = args.action
    if a == "init":
        dest = waves.init_proposal(root, force=args.force)
        print(f"Wrote {project.rel(dest)}: every acceptance criterion is in W1, W2 is empty.\n"
              "Move scope into later waves (AC-level: '<slug>:AC-012', or a whole '<slug>:FEAT-03'), add deferrals "
              "with reason and approver, then a person runs `ekit wave approve --by \"Name\"`.")
        return 0
    if a == "decline":
        waves.decline(root)
        print("Waves declined for this project (recorded in .ekit/project.yaml). Nothing else changes.")
        return 0
    if a == "validate":
        path = waves.PROPOSAL if args.proposal else waves.APPROVED
        plan = waves.load_plan(root, path)
        if plan is None:
            raise EkitError(f"No {path}.")
        errors, warnings = waves.validate(plan, kit, waves.catalog_ids(kit))
        for w in warnings:
            print(f"  ! {w}")
        for e in errors:
            print(f"  x {e}")
        print(f"{path}: {'valid' if not errors else f'{len(errors)} problem(s)'}")
        return 1 if errors else 0
    if a == "approve":
        plan, notes = waves.approve(root, kit, args.by or "")
        for n in notes:
            print(f"  note: {n}")
        print(f"Approved {len(plan.ids)} wave(s) by {plan.data['approved_by']}; current wave {plan.current}. "
              "Commit .ekit/waves.yaml and the proposal.")
        return 0
    if a == "advance":
        cur, nxt, notes = waves.advance(root, kit, args.by or "", carry=args.carry)
        for n in notes:
            print(f"  note: {n}")
        print(f"Moved from {cur} to {nxt}. Run `ekit gate all` and commit .ekit/waves.yaml.")
        return 0
    if a == "scope":
        plan = project.wave_plan
        if plan is None:
            print("waves not in use: specify every acceptance criterion of the feature")
            return 0
        if not args.target:
            raise EkitError("ekit wave scope FEAT-xx [--prd <slug>]")
        slug = Path(project.resolve_prd(args.prd)).name
        s = waves.scope_of_feature(plan, slug, args.target)
        print(f"{slug}:{args.target} in current wave {plan.current}: {', '.join(s['now']) or '-'}")
        if s["earlier"]:
            print(f"  earlier waves (already planned): {', '.join(s['earlier'])}")
        for w, acs in s["later"].items():
            print(f"  later, {w}: {', '.join(acs)}  (not part of this slice)")
        return 0
    # status
    mode = waves.project_mode(root)
    plan = project.wave_plan
    if args.brief:
        print(f"waves: {mode}" + (f" ({plan.current})" if plan else ""))
        return 0
    if plan is None:
        hint = {"undecided": "not decided yet: `ekit wave init` to plan in waves, or `ekit wave decline`",
                "off": "declined for this project", "proposed": f"proposal in {waves.PROPOSAL}, not approved yet"}[mode]
        print(f"Waves: {hint}")
        return 0
    progress = waves.feature_progress(root)
    print(f"Waves: current {plan.current} (approved by {plan.data.get('approved_by')} on {plan.data.get('approved_on')})")
    for w in plan.waves:
        wid = str(w.get("id"))
        acs = plan.acs_of(wid)
        spec = sum(1 for ac in acs if ac in progress)
        green = sum(1 for ac in acs if (progress.get(ac) or {}).get("green"))
        marker = "->" if wid == plan.current else "  "
        roles = ",".join(w.get("profiles") or ["all"])
        print(f" {marker} {wid:<4} {len(acs):>3} AC  specified {spec:>3}  green {green:>3}  profiles {roles:<17} {w.get('goal') or ''}")
    for nid, d in sorted(plan.deferrals().items()):
        due = "DUE NOW" if plan.order(plan.current) >= plan.order(str(d.get("until"))) else f"until {d.get('until')}"
        re_ = f", re-deferred {d['redeferred']}x" if d.get("redeferred") else ""
        print(f"    deferred {nid:<8} {due}{re_}  ({d.get('reason')})")
    errors, _ = waves.validate(plan, kit, waves.catalog_ids(kit))
    if errors:
        print(f"  !! plan no longer valid ({len(errors)} problem(s)); run `ekit wave validate`")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    from . import models
    project = Project.load()
    root, kit = project.root, project.kit
    a = args.action
    if a == "off":
        for n in models.off(root):
            print(n)
        return 0
    if a == "setup":
        found = models.discover(root)
        rec = models.recommend(found)
        current = ((models.load_config(root) or {}).get("tiers") or {})
        chosen: dict[str, str | None] = {}
        given = {"flagship": args.flagship, "standard": args.standard, "light": args.light}
        interactive = _interactive(args) and not all(given.values())
        if interactive:
            print("Models configured in OpenCode (project and global opencode.json):")
            for i, m in enumerate(found, 1):
                ctx = f"{m['context']} tokens" if m.get("context") else "context unknown"
                role = f", OpenCode {m['role']}" if m.get("role") else ""
                print(f"  {i}) {m['id']:<40} {ctx}{role} [{m['source']}]")
            if not found:
                print("  (none found; type model ids as OpenCode expects them, e.g. ollama/qwen3:32b)")
            hints = {"flagship": "decisions and contracts: BRD intake, constitution, landing zone, plan, red",
                     "standard": "volume work the gates check: specify, gherkin, tasks, implement",
                     "light": "OpenCode small_model: titles and summaries"}
            for tier in ("flagship", "standard", "light"):
                default = given[tier] or (current.get(tier) or {}).get("model") or rec.get(tier)
                raw = input(f"{tier:<9} ({hints[tier]})\n          model [{default or 'none'}]: ").strip()
                if raw.isdigit() and 1 <= int(raw) <= len(found):
                    raw = found[int(raw) - 1]["id"]
                chosen[tier] = raw or default
        else:
            for tier in ("flagship", "standard", "light"):
                chosen[tier] = given[tier] or (current.get(tier) or {}).get("model") or (rec.get(tier) if args.recommended else None)
            if not chosen["flagship"] or not chosen["standard"]:
                raise EkitError("Give --flagship and --standard (and optionally --light), or --recommended, or run interactively.")
            chosen["light"] = chosen["light"] or chosen["standard"]
        dest = models.write_config(root, chosen)
        print(f"Wrote {project.rel(dest)}: flagship={chosen['flagship']}, standard={chosen['standard']}, light={chosen['light']}")
        for n in models.apply(root, kit):
            print(f"  {n}")
        print("Commit .ekit/models.yaml and the changed .opencode/ files, then restart OpenCode.")
        return 0
    # show
    rts, notes = models.routes(root, kit)
    if not rts:
        print("Model routing: off (every command uses the session's default model). `ekit models setup` to turn it on.")
        return 0
    files = {**models.command_files(root), **models.agent_files(root)}
    print(f"Model routing ({models.CONFIG}); the model recorded is the one configured, not proof of the one that ran")
    for r in rts:
        where = "" if r.name in files else "   (no file under .opencode/)"
        flag = "  [override]" if r.overridden else ""
        print(f"  {r.kind:<7} {r.name:<26} {r.tier:<9} {r.model or 'session default'}{flag}{where}")
    sm = models.small_model(root, kit)
    print(f"  small_model {'':<26} {'light':<9} {sm or 'session default'}")
    for n in notes:
        print(f"  note: {n}")
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
    sp.add_argument("--allow-src", action="store_true",
                    help="don't also deny production source edits while unfrozen (default: deny them, since the point is to fix the test)")
    sp.set_defaults(fn=cmd_unfreeze)

    sp = sub.add_parser("fix-red", help="unfreeze, temporarily revert the feature's source to its last-red state, "
                                         "run gate red, restore the source — for a frozen test whose own glue is wrong")
    sp.add_argument("feature", nargs="?", help="feature folder, e.g. 001-user-admin (default: the current one)")
    sp.add_argument("--reason", required=True, help="why the test needs fixing; stored in .ekit/freeze.yaml")
    sp.set_defaults(fn=cmd_fix_red)

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

    sp = sub.add_parser("wave", help="optional wave planning: status | init | decline | validate | approve | advance | scope")
    sp.add_argument("action", nargs="?", default="status",
                    choices=["status", "init", "decline", "validate", "approve", "advance", "scope"])
    sp.add_argument("target", nargs="?", help="for scope: the PRD feature, e.g. FEAT-02")
    sp.add_argument("--by", help="approve / advance: the person deciding (recorded)")
    sp.add_argument("--carry", action="store_true", help="advance: move unfinished ACs of the current wave to the next")
    sp.add_argument("--proposal", action="store_true", help="validate the proposal instead of the approved plan")
    sp.add_argument("--prd", help="for scope: docs/requirements/<slug>")
    sp.add_argument("--brief", action="store_true", help="status: one line (used by the agent commands)")
    sp.add_argument("--force", action="store_true", help="init: overwrite an existing proposal")
    sp.set_defaults(fn=cmd_wave)

    sp = sub.add_parser("models", help="optional model routing by tier: show | setup | off")
    sp.add_argument("action", nargs="?", default="show", choices=["show", "setup", "off"])
    sp.add_argument("--flagship", help="model id for the flagship tier, e.g. anthropic/claude-opus-x")
    sp.add_argument("--standard", help="model id for the standard tier")
    sp.add_argument("--light", help="model id for the light tier (OpenCode small_model); default: the standard model")
    sp.add_argument("--recommended", action="store_true", help="setup without prompts: use the recommendation for unset tiers")
    sp.add_argument("--non-interactive", action="store_true", help="never prompt")
    sp.set_defaults(fn=cmd_models)

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
