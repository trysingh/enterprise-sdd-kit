"""ekit — Enterprise SDD Kit CLI."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import __version__, gates, installer, kitsource, logbook
from . import questions as oq
from .project import (FEATURE_DIR_RE, EkitError, Kit, Project, bundled_kit_dir, find_project_root, git,
                      load_yaml, dump_yaml, python_exe)
from .runner import run_profile_command


def _interactive(args: argparse.Namespace) -> bool:
    return not getattr(args, "non_interactive", False) and sys.stdin.isatty()


# --------------------------------------------------------------------------- handlers
def cmd_init(args: argparse.Namespace) -> int:
    installer.init(args.target, stack=args.stack, source=args.source, integration=args.integration,
                   force=args.force, interactive=_interactive(args), extra_specify=args.specify_arg or [],
                   baseline=args.baseline, name=args.name)
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
    if getattr(args, "recontract", False):
        from . import contract
        from .project import dump_yaml, load_yaml
        ledger = project.root / ".ekit" / "ledger" / f"{feature}.yaml"
        data = (load_yaml(ledger) or {}) if ledger.is_file() else {}
        reds = [e for e in (data.get("entries") or []) if e.get("phase") == "red"]
        if not reds:
            raise EkitError(f"No red entry for {feature}: run `ekit gate red` first.")
        reds[-1]["contract"] = contract.contract_from_commit(project.root, feature, reds[-1])
        dump_yaml(data, ledger)
        print(f"{feature}: contract recorded from the red-time commit ({len(reds[-1]['contract']['modules'])} module(s)). "
              "Commit .ekit/ledger.")
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
        print(f"\n{feature}: still not a clean red (see above) — production source has been restored either way.\n"
              "If the error above names something other than AssertionError, the revert most likely went back "
              "further than this fix needs: it reverts the feature's WHOLE production source directory to its "
              "last-red commit, which can also strip out shared code other features added since (or an earlier "
              "shape this feature's own later work changed) that the fixed test now legitimately depends on. "
              "If so, revert only the specific file(s) this feature's test actually exercises by hand instead "
              "(`git checkout <an earlier commit> -- <that one file>`, `ekit gate red`, review, restore, commit) "
              "rather than the whole source tree. Otherwise, fix the test further and run "
              f"`ekit fix-red {feature} --reason \"...\"` again.")
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
        logbook.note_gate(res)
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
    from . import changes
    crs = changes.summary_rows(project.root)
    if crs:
        print("\nChange requests (0.5.0)")
        for r in crs:
            if "error" in r:
                print(f"  {r['id']}: {r['error']}")
            else:
                print(f"  {r['id']:<8} {r['type']:<11} {r['phase']:<6} {r['title'][:50]}"
                      + (f"  -> {', '.join(r['features'])}" if r["features"] else ""))
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
        entries = ((yaml.safe_load(ledger.read_text(encoding="utf-8")) or {}).get("entries") or []) if ledger.is_file() else []
        phases = {e.get("phase") for e in entries}
        cells += ["ok" if "red" in phases else "--", "ok" if "green" in phases else "--"]
        print(f"  {f.name:<28} " + "    ".join(f"{c:<2}" for c in cells) + f"    {'yes' if f.name in frozen else '--'}")
        open_blocked = _open_blocked(entries)
        if open_blocked:
            print(f"    blocked: {open_blocked} open (agent stopped; see `ekit log why {f.name}`)")
    if not features:
        print("  (none yet)")
    return 0


def _open_blocked(entries: list[dict]) -> int:
    """`phase: blocked` entries recorded after the feature's last red or green entry."""
    last = max((i for i, e in enumerate(entries) if e.get("phase") in ("red", "green")), default=-1)
    return sum(1 for e in entries[last + 1:] if e.get("phase") == "blocked")


def cmd_blocked(args: argparse.Namespace) -> int:
    """The agent's way to stop and say why (allowed to it, unlike unfreeze): a ledger entry plus a log event."""
    from . import freeze
    project = Project.load()
    root = project.root
    feature = project.resolve_feature(args.feature).name
    reason = (args.reason or "").strip()
    if not reason:
        raise EkitError('A reason is required: ekit blocked <feature> --reason "..."')
    fields = {
        "reason": reason, "file": args.file, "scenario": args.scenario,
        "git_head": git(root, "rev-parse", "HEAD"), "by": freeze._who(root), "via": logbook.via(),
    }
    ledger = root / ".ekit" / "ledger" / f"{feature}.yaml"
    data = (load_yaml(ledger) if ledger.is_file() else None) or {"feature": feature, "entries": []}
    data.setdefault("entries", []).append({
        "phase": "blocked", "at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(), **fields})
    dump_yaml(data, ledger)
    logbook.append(root, {"kind": "agent.blocked", "feature": feature, **fields})
    print(f"{feature}: blocked recorded in {project.rel(ledger)}. Stop here and tell the user why.\n"
          "A person should review it. If the .feature file itself is wrong, a person runs "
          f"`ekit unfreeze {feature} --reason \"...\"`. If the step glue is wrong and the project uses "
          "`freeze.mode: split`, the agent may fix step bodies in the feature's own test module and the green gate "
          "re-proves them.")
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    root = find_project_root()
    a = args.action
    events = logbook.iter_events(root)
    if a == "verify":
        problems = logbook.verify(root)
        if problems:
            print("\n".join(problems))
            return 1
        print(f"log intact ({logbook.count(root)} events)")
        return 0
    if a == "append":
        raw = args.json if args.json is not None else sys.stdin.read()
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EkitError(f"log append needs a JSON object: {exc}") from None
        if not isinstance(ev, dict):
            raise EkitError("log append needs a JSON object.")
        if not str(ev.get("kind", "")).startswith(("tool.", "agent.")):
            raise EkitError("log append accepts only kinds starting with `tool.` or `agent.` (ekit writes the others itself).")
        ev.setdefault("via", "agent")
        logbook.append(root, ev)
        return 0
    if a == "show":
        if not args.target:
            raise EkitError("ekit log show RUN_ID")
        found = [e for e in events if e.get("run_id") == args.target]
        if not found:
            raise EkitError(f"No events for run {args.target}.")
        print("\n".join(logbook.line(e) for e in found))
        return 0
    if a == "why":
        if not args.target:
            raise EkitError("ekit log why FEATURE")
        feature = args.target
        if feature.isdigit() and len(feature) == 3:
            names = [d.name for d in Project.load(root).feature_dirs() if d.name.startswith(feature + "-")]
            feature = names[0] if len(names) == 1 else feature
        shown = [e for e in events if logbook.touches_feature(e, feature) and (
            (e.get("kind") == "cmd.end" and e.get("gate")) or str(e.get("kind")).startswith("state.")
            or e.get("kind") == "agent.blocked" or (e.get("kind") == "tool.call" and e.get("outcome") not in (None, "ok")))]
        if not shown:
            print(f"No logged events for {feature}.")
        for e in shown:
            print(f"{e.get('ts')} {e.get('via') or '-':<6} {logbook.summary(e)}")
        return 0
    if a == "export":
        for e in events:
            if args.since and str(e.get("ts", "")) < args.since:
                continue
            if args.feature and not logbook.touches_feature(e, args.feature):
                continue
            print(json.dumps(e, ensure_ascii=False, separators=(",", ":")))
        return 0
    # tail
    picked = [e for e in events
              if (not args.feature or logbook.touches_feature(e, args.feature))
              and (not args.kind or str(e.get("kind", "")).startswith(args.kind))
              and (not args.via or e.get("via") == args.via)]
    for e in picked[-args.n:] if args.n > 0 else []:
        print(logbook.line(e))
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


def cmd_constitution(args: argparse.Namespace) -> int:
    from . import constitution
    project = Project.load()
    if args.action == "ratify":
        notes = constitution.ratify(project, name=args.name)
        print("\n".join(notes) if notes else f"{constitution.MEMORY} is already ratified; nothing to fill.")
    state, details = constitution.principles_drift(project)
    print(f"principles I-VIII: {state}" + "".join(f"\n  - {d}" for d in details))
    return 1 if state == "changed" else 0


def cmd_baseline(args: argparse.Namespace) -> int:
    from . import freeze, golden, landing
    project = Project.load()
    root = project.root
    a = args.action
    if a == "install":
        if golden.is_golden(project) and golden.read_lock(root):
            raise EkitError("The golden landing zone is already installed.")
        installer.set_baseline_mode(root, "golden")
        try:
            installer.install_golden(Project.load(root), name=args.name)
        except EkitError:
            installer.set_baseline_mode(root, str(((project.config or {}).get("baseline") or {}).get("mode") or "generate"))
            raise
        installer.install_opencode_assets(Project.load(root))
        print("Installed. Next: `ekit run install`, `ekit gate baseline`, commit, restart OpenCode.")
        return 0
    if not golden.is_golden(project):
        mode = ((project.config or {}).get("baseline") or {}).get("mode") or "generate"
        print(f"Landing zone: {mode} (no golden core). `ekit gate baseline` judges it; "
              f"{landing.status(project)[0]}.")
        return 0 if a in ("status", "drift") else 2
    if a == "unfreeze":
        freeze.unfreeze_baseline(root, args.reason or "")
        print("Golden core unfrozen (recorded in .ekit/freeze.yaml). Restart OpenCode. When the change is reviewed: "
              "`ekit baseline accept --reason \"...\"` (re-fingerprints and re-freezes).")
        return 0
    if a == "accept":
        changed = golden.accept(root, args.reason or "")
        lock = golden.read_lock(root) or {}
        freeze.freeze_baseline(root, list(lock.get("frozen") or []))
        print(("Accepted: " + "; ".join(changed)) if changed else "Nothing differed from the record.")
        print("Golden core re-frozen. Run `ekit gate baseline`, commit .ekit/, restart OpenCode.")
        return 0
    if a == "freeze":
        lock = golden.read_lock(root) or {}
        rules = freeze.freeze_baseline(root, list(lock.get("frozen") or []) or None)
        print(f"Golden core frozen: {len(rules)} deny rule(s) in opencode.json. Restart OpenCode.")
        return 0
    lock = golden.read_lock(root) or {}
    found = golden.drift(root)
    if a == "status":
        st = freeze.load_state(root)
        print(f"Golden landing zone {lock.get('stack')} {lock.get('version')} (installed {str(lock.get('installed_at'))[:10]})")
        print(f"  core: {'frozen' if st.get('baseline') else 'UNFROZEN (a person is changing it)'}, "
              f"{len(lock.get('frozen') or [])} pattern(s); drift: {len(found)} file(s)")
        print(f"  landing zone gate: {' — '.join(landing.status(project))}")
        g = golden.for_project(project)
        if g is not None:
            print(f"  seams: " + "; ".join(f"{k}: {v}" for k, v in g.seams.items()))
    for d in found:
        print(f"  {d.kind:<8} {d.rel}")
    if a == "drift" and not found:
        print("No drift: every golden core file matches .ekit/golden.lock.yaml.")
    return 1 if (a == "drift" and found) else 0


def cmd_feature(args: argparse.Namespace) -> int:
    from . import features, golden
    project = Project.load()
    if args.action == "package":
        feature = features.current(project, args.name, phase="any")
        pkgs = golden.feature_packages(project, feature)
        if not pkgs:
            raise EkitError("Feature packages are a golden landing zone convention; this project has none.")
        print("\n".join(pkgs))   # 0.5.0: a bug fix or enhancement prints the affected feature's package(s)
        return 0
    print(features.current(project, args.name, phase=args.phase))
    return 0


def cmd_change(args: argparse.Namespace) -> int:
    """0.5.0: change requests (bug fixes, enhancements, features) taken from the prompt."""
    from . import changes
    project = Project.load()
    root = project.root
    a = args.action
    if a == "new":
        text = args.text
        if args.file:
            text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        d = changes.new(root, type_=args.type, title=args.title, text=text, ticket=args.ticket, affects=args.affects)
        data = changes.load(d)
        print(f"{data['id']} {project.rel(d)}")
        if changes.PLACEHOLDER in (d / "request.md").read_text(encoding="utf-8"):
            print(f"Paste the request verbatim into {project.rel(d)}/request.md under '{changes.REQUEST_MARKER}'.")
        return 0
    if a == "list":
        rows = changes.summary_rows(root)
        if not rows:
            print("No change requests yet (/speckit.esdlc.change <request>).")
        for r in rows:
            if "error" in r:
                print(f"  {r['id']}: {r['error']}")
                continue
            extra = f" affects {','.join(r['affects'])}" if r["affects"] else ""
            extra += f" supersedes {','.join(r['supersedes'])}" if r["supersedes"] else ""
            print(f"  {r['id']:<8} {r['type']:<11} {r['phase']:<6} {r['title']}"
                  f"{'  -> ' + ', '.join(r['features']) if r['features'] else ''}{extra}")
        return 0
    if a == "show":
        if args.feature:
            hit = changes.for_feature(root, project.resolve_feature(args.feature))
            if not hit:
                print("none: this feature is not a change request (ordinary PRD feature)")
                return 0
            d, data = hit
        else:
            if not args.target:
                raise EkitError("ekit change show CR-0007   (or --feature NNN-slug)")
            d = changes.find(root, args.target)
            data = changes.load(d)
        print(f"{data.get('id')} {data.get('type')}: {data.get('title')}  ({project.rel(d)})")
        print(f"  affects: {', '.join(changes.affected_features(data)) or '-'}")
        print(f"  supersedes: {', '.join(map(str, data.get('supersedes') or [])) or '-'}")
        print(f"  features: {', '.join(changes.features_of(root, d)) or '- (not specified yet)'}")
        if data.get("type") == "bug":
            print("  red: reproduce the bug against the committed code; no stubs, no production edits (RED-BUG-REPRODUCED)")
        return 0
    if a == "candidates":
        text = " ".join([args.target or "", *(args.words or [])])
        found = changes.candidates(root, text)
        if not found:
            print("No existing feature matches; treat it as new, or name the feature yourself.")
        for name, score, hits in found:
            print(f"  {name:<32} {score:>2}  {' '.join(hits)}")
        return 0
    if a == "retire":
        if not args.target or not args.words or not args.by or not args.reason:
            raise EkitError('ekit change retire <feature> SCN-003-04 [SCN-…] --by CR-0007 --reason "..."')
        feature = project.resolve_feature(args.target).name
        for m in changes.retire(project, feature, list(args.words), change=args.by, reason=args.reason):
            print(m)
        return 0
    raise EkitError(f"unknown action {a}")


def cmd_adr(args: argparse.Namespace) -> int:
    from . import features
    project = Project.load()
    print(project.rel(features.new_adr(project.root, " ".join(args.title))))
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
        sp.add_argument("--baseline", choices=["golden", "generate"],
                        help="landing zone: the kit's golden one (default where the stack has one) or generated by the model")
        sp.add_argument("--name", help="project name used in the golden landing zone and constitution (default: folder name)")

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
    sp.add_argument("--recontract", action="store_true",
                    help="0.4.0: record the split-freeze contract for a feature recorded red by an older ekit "
                         "(computed from the committed red-time tests)")
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

    sp = sub.add_parser("constitution", help="ratify (fill placeholders deterministically) | check principles I-VIII")
    sp.add_argument("action", choices=["ratify", "check"])
    sp.add_argument("--name", help="project name (default: folder name)")
    sp.set_defaults(fn=cmd_constitution)

    sp = sub.add_parser("baseline", help="golden landing zone: status | drift | freeze | unfreeze | accept | install")
    sp.add_argument("action", nargs="?", default="status",
                    choices=["status", "drift", "freeze", "unfreeze", "accept", "install"])
    sp.add_argument("--reason", help="unfreeze / accept: why the core changes (recorded)")
    sp.add_argument("--name", help="install: project name (default: folder name)")
    sp.set_defaults(fn=cmd_baseline)

    sp = sub.add_parser("feature", help="current [NAME] [--for red|implement|any]: the one feature to work on, or fail | "
                                        "package [NAME]: its code package")
    sp.add_argument("action", choices=["current", "package"])
    sp.add_argument("name", nargs="?", help="what the user named: NNN-slug or NNN (optional)")
    sp.add_argument("--for", dest="phase", choices=["red", "implement", "any"], default="any")
    sp.set_defaults(fn=cmd_feature)

    sp = sub.add_parser("change", help="change requests from the prompt (0.5.0): new | list | show | candidates | retire")
    sp.add_argument("action", choices=["new", "list", "show", "candidates", "retire"])
    sp.add_argument("target", nargs="?", help="show: CR-0007; retire: the feature folder whose scenario is retired; "
                                              "candidates: first word of the request")
    sp.add_argument("words", nargs="*", help="candidates: the request text; retire: SCN ids")
    sp.add_argument("--type", choices=["bug", "enhancement", "feature"], help="new: kind of change")
    sp.add_argument("--title", help="new: short title")
    sp.add_argument("--text", help="new: the request, verbatim")
    sp.add_argument("--file", help="new: read the request from a file, or - for stdin")
    sp.add_argument("--ticket", help="new: tracker id, e.g. JIRA-123")
    sp.add_argument("--affects", action="append", help="new: existing feature folder(s) it changes (repeatable or comma list)")
    sp.add_argument("--feature", help="show: the change a feature folder implements")
    sp.add_argument("--by", help="retire: the change request, CR-0007")
    sp.add_argument("--reason", help="retire: why (audited)")
    sp.set_defaults(fn=cmd_change)

    sp = sub.add_parser("adr", help='new "Title": create docs/adr/NNNN-title.md with the next free number')
    sp.add_argument("action", choices=["new"])
    sp.add_argument("title", nargs="+")
    sp.set_defaults(fn=cmd_adr)

    sp = sub.add_parser("blocked", help="agent: stop and record why a frozen test or scenario cannot be satisfied")
    sp.add_argument("feature", nargs="?", help="feature folder, e.g. 001-user-admin (default: the current one)")
    sp.add_argument("--reason", required=True, help="what is wrong, concretely")
    sp.add_argument("--file", help="the file the problem is in")
    sp.add_argument("--scenario", help="scenario id, e.g. SCN-003")
    sp.set_defaults(fn=cmd_blocked)

    sp = sub.add_parser("log", help="action log: tail | show RUN_ID | why FEATURE | export | verify | append")
    sp.add_argument("action", choices=["tail", "show", "why", "export", "verify", "append"])
    sp.add_argument("target", nargs="?", help="show: run id; why: feature")
    sp.add_argument("-n", type=int, default=50, help="tail: how many events (default 50)")
    sp.add_argument("--feature", help="tail / export: only this feature")
    sp.add_argument("--kind", help="tail: kind prefix, e.g. cmd, state, tool.call")
    sp.add_argument("--via", choices=["agent", "person"], help="tail: who acted")
    sp.add_argument("--since", help="export: ISO timestamp or date")
    sp.add_argument("--json", help="append: the event as a JSON object (default: read stdin)")
    sp.set_defaults(fn=cmd_log)

    sp = sub.add_parser("doctor", help="check tools, kit integrity and installation")
    sp.set_defaults(fn=cmd_doctor)
    return p


@dataclass
class _LogRun:
    """cmd.start / cmd.end events around one command (see logbook)."""
    root: Path
    cmd: str
    args: list[str]
    feature: str | None
    run_id: str
    t0: float

    @classmethod
    def begin(cls, args: argparse.Namespace, argv: list[str]) -> _LogRun | None:
        if args.cmd == "log":
            return None            # reads are not logged; `log append` writes its own event
        try:
            root = find_project_root()
            if not (root / ".ekit").is_dir():
                return None
            rest = argv[argv.index(args.cmd) + 1:] if args.cmd in argv else argv
            feature = next((a for a in rest if not a.startswith("-") and FEATURE_DIR_RE.match(a)), None)
            run = cls(root, args.cmd, logbook.redact_argv(rest), feature, uuid.uuid4().hex, time.monotonic())
            logbook.CURRENT.clear()
            logbook.append(root, {"kind": "cmd.start", **run._fields()})
            return run
        except (EkitError, OSError):
            return None

    def _fields(self) -> dict:
        return {
            "run_id": self.run_id, "cmd": self.cmd, "args": self.args, "feature": self.feature,
            "via": logbook.via(), "actor": logbook.actor(self.root), "session": os.environ.get("EKIT_SESSION"),
            "ekit": __version__, "git_head": git(self.root, "rev-parse", "--short", "HEAD"),
            "dirty": bool(git(self.root, "status", "--porcelain", "--", ".", ":(exclude).ekit/logs")),
        }

    def end(self, rc: int, error: str | None) -> None:
        gate = logbook.CURRENT.pop("gate", None)
        fields = self._fields()
        if gate:
            fields["feature"] = gate.get("feature") or fields["feature"]
            fields["gate"] = {k: gate[k] for k in ("name", "result", "checks", "findings")}
        logbook.append(self.root, {"kind": "cmd.end", **fields, "exit": rc,
                                   "duration_ms": int((time.monotonic() - self.t0) * 1000), "error": error})


def _run(args: argparse.Namespace) -> tuple[int, str | None]:
    try:
        return int(args.fn(args) or 0), None
    except EkitError as exc:
        print(f"ekit: {exc}", file=sys.stderr)
        return 2, str(exc)
    except KeyboardInterrupt:
        print("\nekit: interrupted", file=sys.stderr)
        return 130, "interrupted"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
        except (ValueError, OSError):
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    run = _LogRun.begin(args, argv)
    rc, error = 1, "unexpected error"
    try:
        rc, error = _run(args)
        return rc
    finally:
        if run is not None:
            run.end(rc, error)


if __name__ == "__main__":
    sys.exit(main())
