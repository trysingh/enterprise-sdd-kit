# Enterprise SDD Kit (`ekit`) — MVP1

One command turns a new or existing repository into an enterprise landing zone for
**GitHub Spec Kit + OpenCode**, running a deterministic
**BRD → PRD → spec → Gherkin → plan → tasks → red → green** pipeline with a generic
engineering baseline.

```
ekit init my-project --stack fastapi-react      # greenfield
ekit adopt --stack springboot-vanilla           # brownfield, run inside the repo
```

This replaces the manual `specify init` / `specify integration install opencode` steps.

---

## What you get

| Layer | What it is | Where it ends up |
|---|---|---|
| **esdlc extension** | New Spec Kit commands: `/speckit.esdlc.brd`, `.questions`, `.baseline`, `.gherkin`, `.red` | `.specify/extensions/esdlc`, `.opencode/commands` |
| **enterprise-baseline preset** | Enterprise constitution; traceability + NFR sections appended to spec/plan/tasks templates; gates wrapped around core `/speckit.specify`, `.plan`, `.tasks`, `.implement` | `.specify/presets/…`, `.opencode/commands` |
| **NFR catalogue** | 37 generic NFRs (22 platform-scope, 15 feature-scope): security, API, observability, reliability, data, runtime environment, performance, quality, delivery, UX, docs | `.ekit/kit/baseline/nfr-catalog.yaml` |
| **Stack profiles** | Per stack: toolchain, layout, required paths, argv commands, BDD wiring, how each NFR is met, agent rules | `.ekit/kit/profiles/**` |
| **Gate policy** | YAML gates with stable check ids, run by `ekit gate` | `.ekit/kit/policy/gates.policy.yaml` |
| **OpenCode wiring** | Managed block in `AGENTS.md` (your own content is kept), `requirements-analyst` and `test-author` agents | `AGENTS.md`, `.opencode/agents` |

Stacks in MVP1: `fastapi-jinja`, `fastapi-react`, `springboot-vanilla`, `springboot-react`.

## Install (Windows, macOS, Linux)

Prerequisites: Python ≥ 3.11, `uv`, `git`, Spec Kit, OpenCode.

```
uv tool install specify-cli
npm install -g opencode-ai
uv tool install ./enterprise-sdd-kit            # or: uv tool install git+https://<your-git>/enterprise-sdd-kit
ekit doctor
```

`ekit` needs only PyYAML. It uses Spec Kit's **Python** scripts (`--script py`), argv-list
commands (no shell), `{mvnw}` → `mvnw.cmd` on Windows / `./mvnw` elsewhere, and resolves
`npm`/`uv` through PATH, so the same commands and gates work on every OS.

## Choosing the kit source (decided at runtime)

`ekit init` asks where the kit should come from, or you pass `--source`:

| Source | Example | Use when |
|---|---|---|
| `bundled` | `--source bundled` | trying it out; offline |
| local folder | `--source D:\kits\enterprise-sdd-kit` | a clone of your org's kit repo |
| git | `--source git+https://git.example.com/eng/sdd-kit.git@v0.2.0` | teams; pin a tag |

You can also set `EKIT_KIT_SOURCE`. Whatever the source, the kit is **copied into
`.ekit/kit` and pinned** in `.ekit/kit.lock.yaml` (source, tag, commit, sha256). Commit both:
everyone and every CI run then uses identical rules. `ekit doctor` detects local edits to the
vendored kit; `ekit upgrade [--source …]` re-fetches, re-pins and re-applies.

### What is pinned, and what is not

| Part | Where it lives | Pinned by | Changes when |
|---|---|---|---|
| **Rules**: gate policy, NFR catalogue, stack profiles, templates, agent rules | `.ekit/kit/` in the repository (committed) | `.ekit/kit.lock.yaml`: source, resolved commit, sha256 | someone runs `ekit upgrade` and commits the result |
| **Check engine**: the `ekit` CLI that reads those rules and judges the files (`checks.py`, `gates.py`, step scan, fingerprints) | each machine's uv tool folder | `ekit.version` in `.ekit/kit.lock.yaml` (since ekit 0.1.4), plus the kit's allowed range `requires.ekit` (e.g. `>=0.1.5,<0.2`) | a developer reinstalls the CLI |

Both parts decide a gate result. Identical rules judged by two different CLI versions can disagree,
because check logic changes between releases (0.1.1 changed how tags are read, 0.1.2 added
`RED-STEPS-ASSERT` and `GREEN-TESTS-UNCHANGED`, 0.1.5 stopped counting skipped scenarios as red). So:

- **One CLI version per project.** `ekit init` and `ekit upgrade` record the running CLI version in the lock.
  Everyone, and CI, installs exactly that version.
- **Install by tag.** Tag the kit repository with the CLI version (e.g. `v0.1.5`; one tag then fixes both the CLI
  and the kit it ships) and install it with `uv tool install --force git+https://…/sdd-kit.git@v0.1.5`.
- **Mismatch is visible.** `ekit doctor` fails the row *ekit CLI matches the project pin*, `ekit status` prints a
  `!!` line, and every gate report (text, JSON and JUnit) carries a note naming both versions.
- **CI refuses to judge with the wrong CLI.** Set `EKIT_REQUIRE_PINNED_CLI=1` in the pipeline: a gate then exits 2
  before running any check if the installed CLI differs from the pin.
- **Moving the team to a new CLI is a reviewed change.** Install the new CLI, run `ekit upgrade` (re-vendors the
  kit and re-pins the CLI), commit `.ekit/`, and have everyone reinstall the same tag after the merge.
- **`bundled` couples the two.** With `--source bundled`, `ekit upgrade` vendors the kit shipped inside the CLI you
  are running, so whoever upgrades also chooses the kit version. Teams should prefer a git source pinned to a tag.
- **Evidence names its judge.** Every red and green ledger entry records `ekit_version` next to `kit_version`.

## The pipeline

| # | In OpenCode | Produces | Gate (exit 1 on failure) |
|---|---|---|---|
| 0 | `/speckit.constitution` | constitution seeded with fixed principles I–VIII | — |
| 1 | `/speckit.esdlc.baseline` | landing-zone skeleton (greenfield) or gap assessment (brownfield) + `docs/engineering/baseline-conformance.md` | `baseline` |
| 2 | `/speckit.esdlc.brd <file>` | `docs/requirements/<slug>/brd.md` (BR-###), `prd.md` (FEAT-##, AC-###), `open-questions.yaml` | `intake` |
| 3 | `/speckit.esdlc.questions` | answers recorded, PRD updated | `ready` |
| 4 | `/speckit.specify FEAT-01` | `spec.md` + `trace.yaml` | `ready` (before), `spec` (after) |
| 5 | `/speckit.esdlc.gherkin` | `features/*.feature` tagged `@SCN-NNN-nn @AC-xxx` | `scenarios` |
| 6 | `/speckit.plan` | plan with **Engineering Baseline Conformance** table | `plan` |
| 7 | `/speckit.tasks` | test-first tasks linked to scenarios | — |
| 8 | `/speckit.esdlc.red` | step definitions + unit tests, all failing; ledger entry | `red` |
| 9 | `/speckit.implement` | code | `red-recorded` (before), `green` (after) |

### Open questions with the product manager

```
ekit questions list
ekit questions export            # -> docs/requirements/<slug>/questions-for-review.csv (opens in Excel)
ekit questions import answers.csv
ekit gate ready
```

Blocking questions that are open **or deferred** stop `/speckit.specify` for that PRD. An answer to a blocking
question must name who decided (`answered_by`): `ekit questions import` refuses a CSV row without it, and
`ekit gate ready` fails on one already in the register.

### What the gates actually check

- **intake**: files exist; BR ids present; AC ids unique; every BR cited by an AC or listed out of scope; question register valid.
- **ready**: no open/deferred blocking question; every answered blocking question names `answered_by`; no `[TBD…]` / `[NEEDS CLARIFICATION` in the PRD.
- **spec**: `trace.yaml` valid and points at real ACs; every AC referenced in `spec.md`; no clarification markers; with an approved wave plan, every AC is in the current or an earlier wave (`SPEC-WAVE-SCOPE`).
- **scenarios**: `.feature` files parse; each scenario has exactly one `@SCN-<feature>-nn`, unique repo-wide; every AC is tagged on ≥1 scenario.
- **plan**: every applicable **feature-scope** NFR has a row `Addressed | N/A | Waived`; evidence/justification present; `Waived` cites an ADR (`ADR-0007` or `docs/adr/0007-….md`; a date is not an ADR reference); with an approved wave plan, `Deferred (W2)` for an NFR the plan defers until W2.
- **baseline**: same for **platform-scope** NFRs in `baseline-conformance.md`; profile `required_paths` exist; **ENV-01** environment isolation (below); lint runs.
- **red**: first scans the step modules (`RED-STEPS-ASSERT`, pytest-bdd): a step whose body is `pass`, `...`, a docstring or `assert True` is an error, as is an absolute path in `scenarios()`. Then runs the acceptance suite(s); every scenario of the feature appears in the Cucumber-JSON report and **fails** (a scenario that passes before implementation is an error; undefined, pending, ambiguous or **skipped** scenarios are errors, because only an observed failure proves the test can fail). Writes `.ekit/ledger/<feature>.yaml` with git HEAD and a sha256 fingerprint of the feature files and the test modules bound to them.
- **green**: red was recorded first for every scenario (a ledger status of `failed`); the feature files and bound test modules are unchanged since red (`GREEN-TESTS-UNCHANGED`); all scenarios pass and the suites exit 0 (no regressions); unit, lint, coverage pass; SCA and unchecked tasks warn.

Output formats: `--format text|json|junit` and `--out file`. JUnit is understood by GitHub
Actions, GitLab, Azure DevOps and Jenkins without plugins, so taking a gate to CI later is one
step: `ekit gate green --format junit --out reports/gate-green.xml`.

### Relaxing a check (reviewable, never silent)

`.ekit/policy.overrides.yaml`:

```yaml
overrides:
  GREEN-SCA:
    severity: warn
    reason: "Vendor fix for CVE-XXXX pending; JIRA-123"
    approved_by: "Security Architect"
    expires: 2026-12-31
```

Every override needs a `reason`, a named approver (`approved_by`) and an `expires` date. An entry missing any of
the three, or past its expiry, is ignored and the gate report says why (text, JSON and JUnit), so the check runs
at its policy severity again. Expiry is how a relaxation turns back into a failure without anyone remembering
to remove it.

## Frozen tests and step quality

Red proves a test *fails*, not that it is *good*. Two deterministic guards close that gap:

- **`RED-STEPS-ASSERT`** rejects steps that cannot fail. A `Then` whose body is `pass` lets a scenario go
  green with the wrong behaviour, because the scenario was only red for an earlier reason. A deliberate
  no-op is allowed with `# ekit: allow-empty-step <reason>` on the step, so the exception shows up in review.
  The scan is implemented for pytest-bdd; for Cucumber-JVM and cucumber-js the gate prints an info line and
  step bodies must be reviewed by hand.
- **`GREEN-TESTS-UNCHANGED`** compares the files recorded at red with the files now. Editing a recorded test
  to get green fails the gate. Covered: the feature's `.feature` files and the test modules that name them or
  their `@SCN-<NNN>-` ids. Not covered: shared helpers and `conftest.py`, so review changes to those.

### Edit protection: the agent cannot touch frozen files

Detecting a change after the fact is not the same as preventing it. `ekit` therefore owns a set of
`permission.edit` deny rules in the project's `opencode.json`, which OpenCode enforces on the agent's
edit, write and patch tools:

| Rule | Set when | Lifted by |
|---|---|---|
| `.ekit/*`, `opencode.json`, `.opencode/*` | `ekit init`, `sync`, `upgrade` | never (humans edit these outside the agent) |
| `specs/<feature>/features/*` and the test modules bound to the feature | `ekit gate red` passes | `ekit unfreeze <feature> --reason "..."` |

Since 0.2.0 ekit also owns `permission.bash` deny rules for the commands that record a person's decision:
`ekit unfreeze`, `ekit upgrade`, `ekit wave approve|advance|decline` and `ekit models …`. The agent's shell
tool cannot run them; it tells the user the command instead. Running them through another wrapper
(`uv run ekit …`, a script) is not covered, and the records they write name who acted.

State is `.ekit/freeze.yaml` (commit it): the frozen paths and a history of every unfreeze with reason, who and
when. Your own rules and settings in `opencode.json` are kept; ekit rewrites only the rules it owns, after the
catch-all, because OpenCode applies the last matching rule. `ekit status` shows a `frozen` column,
`ekit doctor` verifies the rules are present, and `ekit freeze [feature]` re-applies them (for example after
upgrading a project that was already red).

Limits: the rules cover the edit tools, not shell commands (`sed -i`, scripts), and OpenCode may read its config
only at startup, so restart it after a freeze or unfreeze. `GREEN-TESTS-UNCHANGED` is the backstop for both.
`opencode.json` must be strict JSON (no comments); otherwise ekit stops and prints the rules to add by hand.
`opencode.jsonc` is not managed.

If a recorded test turns out to be wrong: `ekit unfreeze <feature> --reason "..."`, put the code back to its red
state (stubs), fix the test, and run `ekit gate red` again; it records new fingerprints and freezes again. A
reviewed exception without going back to red is an entry in `.ekit/policy.overrides.yaml` for
`GREEN-TESTS-UNCHANGED` with a reason, approver and expiry.

pytest-bdd quirk worth knowing: a scenario whose *first* step has no step definition is left out of
pytest-bdd's Cucumber JSON, and one with a later undefined step is recorded as passed, although pytest fails
the test either way. The gate messages say so; the pytest output (`StepDefinitionNotFoundError`) is the
source of truth.

## Environment isolation (ENV-01)

Every stack must install dependencies only into a project-local environment, with the runtime
version pinned in a committed file. `ekit gate baseline` and `ekit gate green` check it.

| Stack part | Environment | Version pin | Created by |
|---|---|---|---|
| FastAPI (+ Jinja) | `.venv` managed by uv (`pyvenv.cfg` must exist) | `.python-version` | `ekit run install` → `uv sync --locked` |
| React | local `node_modules` | `.nvmrc` + `engines` | `ekit run install` → `npm ci` |
| Spring Boot (+ vanilla) | Maven wrapper; build output in `target/` | `.mvn/wrapper/maven-wrapper.properties` + enforcer `requireJavaVersion` | Maven wrapper |

The check fails when:
- the pin file is missing;
- the environment folder is not ignored by the repository's own `.gitignore`;
- any file inside it is committed;
- it isn't a real virtualenv;
- the venv's Python doesn't match `.python-version`.

All Python commands run through `uv run --locked`, so the global interpreter is never used, and a
`pyproject.toml`/`uv.lock` mismatch fails instead of silently re-resolving. You never need to
activate the venv. `ekit init` adds the environment folders to `.gitignore`.

## Optional: waves (deliver as several MVPs)

Off unless you turn it on. A product can be delivered in **waves**: W1 shows the overall face of the
system (shell, sign-in, one working happy path per major feature, minimal frontend and backend), later
waves deepen it, and new BRDs are placed into waves as they arrive.

- Planned per acceptance criterion: `loan:AC-012`, or `loan:FEAT-03` for all of a feature's ACs. A wave
  slice of a feature becomes its own Spec Kit feature folder, so frozen tests and the ledger work as before.
- `ekit wave init` writes a proposal (`docs/planning/waves.proposed.yaml`) with every AC in W1. People
  (and the agent, as a helper) move scope into later waves and add deferrals with a reason and approver.
- A person approves: `ekit wave approve --by "Head of Product"` validates the proposal and writes
  `.ekit/waves.yaml`, listing every AC explicitly. Every AC of every PRD must be in exactly one wave, so the
  ACs of a new or changed BRD have to be placed before they can be specified.
- `ekit wave advance --by NAME` moves to the next wave once every AC of the current one has a green feature
  (`--carry` moves unfinished ACs on, recorded). Deferred NFRs of the new wave become required.
- Gates: `spec` refuses ACs of a later wave; `Deferred (W2)` is accepted only while W2 is in the future and
  never for the non-deferrable NFRs in `policy/waves.policy.yaml`; profiles not active in the current wave
  (e.g. a backend-only W1) are skipped and named in every gate report.
- `ekit wave decline` records that the project does not use waves, so the BRD command stops asking.

## Optional: model tiers

Off unless you turn it on. The kit routes each OpenCode command and agent to a **tier**
(`policy/models.policy.yaml`); the project picks the model for each tier with `ekit models setup`
(`.ekit/models.yaml`).

| Tier | Commands |
|---|---|
| flagship | `/speckit.esdlc.brd`, `/speckit.constitution`, `/speckit.esdlc.baseline`, `/speckit.plan`, `/speckit.esdlc.red`; agents `requirements-analyst`, `test-author` |
| standard | `/speckit.specify`, `/speckit.clarify`, `/speckit.esdlc.questions`, `/speckit.esdlc.gherkin`, `/speckit.tasks`, `/speckit.implement`, `/speckit.analyze`, `/speckit.checklist` |
| light | OpenCode `small_model` |

ekit writes `model:` into the command and agent frontmatter (OpenCode's per-command override) and a banner
so the agent starts each routed command with `[ekit] tier: flagship · model: <id>`. `ekit sync` re-applies it
after Spec Kit regenerates command files; `ekit doctor` reports files where it is missing. Red and green
ledger entries record `model_tier` and `model_configured`: the configured model, not proof of the one that
ran (the OpenCode UI can still switch models). A temporary downgrade goes in `overrides:` with `reason`,
`approved_by` and `expires`. `ekit models off` removes everything ekit wrote.

## Useful commands

```
ekit status                 # PRDs, open questions, per-feature gate state
ekit context [--nfr feature|platform] [--json]   # what agents read: stack, rules, NFRs + how
ekit run lint|unit|acceptance|coverage|sca       # same command on every OS
ekit gate all
ekit sync                   # re-apply pinned kit (after editing nothing but wanting a refresh)
ekit freeze [feature]        # re-apply edit protection for a red feature (gate red does it)
ekit unfreeze [feature] --reason "..."   # lift it, audited in .ekit/freeze.yaml
ekit upgrade --source git+https://…@v0.3.0
EKIT_REQUIRE_PINNED_CLI=1 ekit gate green   # CI: refuse to judge with a CLI other than the pinned one
ekit wave [status|init|validate|scope FEAT-xx]   # optional waves (approve / advance / decline: a person)
ekit models [show|setup|off]                     # optional model tiers (a person)
```

## Adding a stack

1. Add `profiles/<backend|frontend>/<name>/profile.yaml` (copy the closest one). Commands are argv
   lists; the acceptance command must write Cucumber JSON to `bdd.report`; scenarios are read from
   `specs/` and never copied.
2. Add a stack entry in `kit.yaml` with `profiles` and `roots`.
3. Bump `metadata.version`, tag the kit repo, `ekit upgrade` in projects that want it.

Regulatory overlays (MVP2) slot in the same way: extra NFRs under `overlays:` plus profile
`controls` for them.

## Repository layout

```
src/ekit/                 CLI (gates, checks, kit source, installer, questions, waves, models)
src/ekit/kit/             the kit itself (this is what gets vendored into projects)
  kit.yaml                manifest: stacks, components, version
  baseline/               NFR catalogue
  profiles/               stack profiles
  policy/                 gate policy, wave policy, model routing policy
  extension/esdlc/        Spec Kit extension (commands + templates)
  preset/enterprise-baseline/  Spec Kit preset (template appends + command wraps)
  opencode/               AGENTS.md block + agents
tests/                    unit tests (pytest)
docs/design/              design notes per release
```

## Versions

| ekit | kit | Change |
|---|---|---|
| 0.1.1 | 0.1.2 | Cucumber JSON reader accepts tags with and without `@` (pytest-bdd writes them without). |
| 0.1.2 | 0.1.3 | `RED-STEPS-ASSERT`, `GREEN-TESTS-UNCHANGED`, clearer undefined-step messages, feature lookup in command text, agent rules to extend (never rewrite) the landing zone and not edit frozen tests. The kit declares `requires.ekit >= 0.1.2`; an older CLI refuses it. |
| 0.1.3 | 0.1.4 | Edit protection: ekit-managed `permission.edit` deny rules in `opencode.json`, `ekit freeze` / `unfreeze`, `frozen` column in `status`, doctor check. Requires `ekit >= 0.1.3`. |
| 0.1.5 | 0.1.6 | Governance fixes found by validating the quiz against the code: `RED-RUN` rejects skipped scenarios and `ledger.red_first` counts only `failed` entries; `Waived` needs a real ADR reference (a date such as `2026-12` no longer satisfies it); overrides need `reason`, `approved_by` and `expires`; a blocking question answered without `answered_by` fails `ready` (and `intake`) and is refused by `questions import`. Requires `ekit >=0.1.5,<0.2`. |
| 0.2.0 | 0.2.0 | Optional **waves** (`ekit wave …`, `.ekit/waves.yaml`, AC-level scope, `SPEC-WAVE-SCOPE`, `Deferred (Wn)`, non-deferrable NFRs, inactive profiles skipped) and optional **model tiers** (`ekit models …`, red on flagship by default, frontmatter injection on sync, ledger records the configured model). Approval commands denied to the agent's shell tool. Both features are off unless configured. Requires `ekit >=0.2.0,<0.3`. Design: `docs/design/0.2.0-waves-and-model-tiers.md`. |
| 0.1.4 | 0.1.5 | CLI version pinning: `kit.lock.yaml` records the CLI version (`ekit.version`); `doctor` fails on a mismatch, `status` and every gate report show it, `EKIT_REQUIRE_PINNED_CLI=1` makes gates refuse to run with another CLI; red/green ledger entries record `ekit_version`; `requires.ekit` accepts ranges (`>=0.1.4,<0.2`, also `>`, `<=`, `==`) and the kit declares an upper bound. Requires `ekit >=0.1.4,<0.2`. |

Upgrade: `uv tool install --reinstall ./enterprise-sdd-kit` (or `--force git+…@<tag>`), then in each project
`ekit upgrade` and commit `.ekit/`. Projects vendored before 0.1.4 have no CLI pin: `ekit doctor` says so until
`ekit upgrade` records one.

Moving to 0.1.5 can turn existing results red on purpose: overrides without `approved_by`/`expires` stop
applying, `Waived` rows that cite only a date fail, and a feature whose red ledger shows `skipped` instead of
`failed` must be taken back to red (`ekit unfreeze … --reason`, stubs, `ekit gate red`). Run `ekit gate all`
after `ekit upgrade` and fix what it reports in the same reviewed change.

Moving to 0.2.0 changes nothing for projects that use neither waves nor model tiers, except that
`opencode.json` gains the `permission.bash` deny rules (restart OpenCode after `ekit upgrade`).

## Status of MVP1

Verified against Spec Kit 1.2.7 (source build) on Linux: greenfield `init`, brownfield `adopt`,
kit from bundled / folder / git tag, extension + preset install, command wrapping and template
composition, constitution seeding, every gate pass/fail path, red→green ledger, CSV question
round-trip, overrides, tamper detection, upgrade. Exercised on macOS by a real user run with
FastAPI + pytest-bdd (which found the tag-format and empty-step gaps fixed in 0.1.1 and 0.1.2). Not yet
exercised: Windows hosts, the Spring Boot and React toolchains, and agent output quality on smaller models,
which can loop or rewrite baseline code; the gates catch it, they do not prevent it.

0.2.0 (waves, model tiers) is covered by unit and CLI tests but has not yet been run against a live Spec Kit +
OpenCode install: confirm on the first project that Spec Kit writes its OpenCode commands to `.opencode/commands/`
(or `.opencode/command/`) and that `ekit models show` lists them without "(no file under .opencode/)".
