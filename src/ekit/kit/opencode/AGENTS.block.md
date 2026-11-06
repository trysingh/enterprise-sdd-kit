<!-- ekit:begin (managed by enterprise-sdd-kit; edit outside this block, `ekit sync` rewrites it) -->
# Enterprise SDD rules

This repository follows **BRD → PRD → spec → Gherkin → plan → tasks → red → green**, driven by
Spec Kit commands and enforced by `ekit gate <id>`. Gates are the source of truth: if a gate
fails, fix the artifact and re-run; never skip, bypass or edit the policy.

## Pipeline

| Step | Command | Gate |
|------|---------|------|
| Landing zone (once) | `/speckit.esdlc.baseline` | `ekit gate baseline` |
| BRD → PRD + questions | `/speckit.esdlc.brd <brd file>` | `ekit gate intake --prd docs/requirements/<slug>` |
| Answer questions | `/speckit.esdlc.questions` | `ekit gate ready --prd …` |
| PRD feature → spec | `/speckit.specify FEAT-01` | `ekit gate spec` |
| Spec → Gherkin | `/speckit.esdlc.gherkin` | `ekit gate scenarios` |
| Plan | `/speckit.plan` | `ekit gate plan` |
| Tasks | `/speckit.tasks` | — |
| Failing tests | `/speckit.esdlc.red` | `ekit gate red` |
| Code | `/speckit.implement` | `ekit gate green` |

## Non-negotiables

- Never invent business facts. Unknowns go to `docs/requirements/<slug>/open-questions.yaml`.
- No production behaviour before `ekit gate red` has recorded failing tests for it.
- Never edit `.feature` files or weaken assertions to make a test pass. After `ekit gate red` the feature files are
  frozen. The bound acceptance test module is frozen too under strict freeze; under split freeze (golden projects) you
  may fix step BODIES only (wrong method, object or return value), never decorators, patterns, `Then` assertions or
  expected values, and `ekit gate green` re-proves the amended tests red against the red-time code. A wrong
  scenario, binding or expected value is reported with `ekit blocked`, not edited.
- If an edit is refused by a permission rule, stop and report which file and why you needed it. Never route around it
  with shell redirection, `sed`, or scripts.
- Extend the landing zone, never rewrite it: do not delete or replace existing behaviour in baseline modules.
- Every test step sets up state or asserts behaviour. No `pass` or empty step bodies. Every step function must be
  self-contained: never assume a dict key or fixture value was set by a step that belongs to a *different* scenario.
- A failing red scenario must fail on an assertion (or a 501/404), never error out of the test itself (a `KeyError`,
  an undefined step, a typo). If you were sent back to fix a specific frozen test after `ekit unfreeze`, edit only
  the named file(s) that turn — no production code, no other open tasks, even ones still unchecked.
- Never put secrets, tokens or real customer data in code, tests, fixtures or logs.
- Run tools through `ekit run <command>` (lint, unit, acceptance, coverage, sca) so the same
  commands work on Windows and POSIX.
- Use `ekit context` whenever you need the stack, layout, NFRs or rules.
- Which feature to work on is decided by `ekit feature current --for red|implement "<what the user said>"`, never by
  you: use the folder it prints; if it fails, show its message and stop.
- ADRs: `ekit adr new "Title"` (takes the next free number). Never number an ADR by hand.
- Never run `ekit unfreeze`, `ekit fix-red`, `ekit upgrade`, `ekit wave approve|advance|decline`, `ekit models …` or
  `ekit baseline unfreeze|accept|install`: they record a person's decision. Tell the user the exact command instead. (`opencode.json` denies them to your
  shell tool.)
  While a feature is unfrozen, its production source directories are usually also denied to your edit tool until
  it's re-frozen — that's by design (see the previous bullet), not a bug to work around.
- If a frozen test or scenario cannot be satisfied and is not yours to change, stop and run
  `ekit blocked <feature> --reason "..." [--file PATH] [--scenario SCN-ID]`, then tell the user. Do not work around it.
  Your tool calls and `ekit` runs are logged (`ekit log tail`); that log is read by reviewers.
- Waves (if `ekit wave status --brief` says `on`): work only on acceptance criteria of the current wave
  (`ekit wave scope FEAT-xx`). An NFR may be `Deferred (Wn)` in a conformance table only if the approved plan defers it.
- If a command starts with an **ekit model routing** note, begin your first reply with the line it gives.

## Stack: {stack}

Profiles: {profiles}

{agent_rules}
<!-- ekit:end -->
