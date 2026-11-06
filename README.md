# Enterprise SDD Kit (`ekit`) — MVP1 (ekit 0.7.2)

One command turns a new or existing repository into an enterprise landing zone for
**GitHub Spec Kit + OpenCode**, running a deterministic
**BRD → PRD → spec → Gherkin → plan → tasks → red → green** pipeline with a generic
engineering baseline.

```
ekit init my-project --stack fastapi-jinja      # greenfield; installs the golden landing zone (0.3.0)
ekit init my-project --stack fastapi-react      # greenfield; the landing zone is generated
ekit adopt --stack springboot-vanilla           # brownfield, run inside the repo
```

and then, in OpenCode, either a whole BRD or a single request typed in chat (0.5.0):

```
/speckit.esdlc.brd docs/inbox/Loan-BRD-v3.docx
/speckit.esdlc.change bug: after I open a chat the unread badge still shows 3
```

This replaces the manual `specify init` / `specify integration install opencode` steps.

---

## What you get

| Layer | What it is | Where it ends up |
|---|---|---|
| **esdlc extension** | New Spec Kit commands: `/speckit.esdlc.brd`, `.change` (0.5.0), `.questions`, `.design` and `.slice` (0.7.0), `.baseline`, `.gherkin`, `.red` | `.specify/extensions/esdlc`, `.opencode/commands` |
| **enterprise-baseline preset** | Enterprise constitution; traceability + NFR sections appended to spec/plan/tasks templates; gates wrapped around core `/speckit.specify`, `.plan`, `.tasks`, `.implement` | `.specify/presets/…`, `.opencode/commands` |
| **NFR catalogue** | 37 generic NFRs (22 platform-scope, 15 feature-scope): security, API, observability, reliability, data, runtime environment, performance, quality, delivery, UX, docs | `.ekit/kit/baseline/nfr-catalog.yaml` |
| **Stack profiles** | Per stack: toolchain, layout, required paths, argv commands, BDD wiring, how each NFR is met, agent rules | `.ekit/kit/profiles/**` |
| **Gate policy** | YAML gates with stable check ids, run by `ekit gate` | `.ekit/kit/policy/gates.policy.yaml` |
| **OpenCode wiring** | Managed block in `AGENTS.md` (your own content is kept), `requirements-analyst` and `test-author` agents | `AGENTS.md`, `.opencode/agents` |
| **Golden landing zone** (0.3.0, `fastapi-jinja`) | A reviewed, pre-built landing zone that meets every platform-scope NFR: frozen core, shared pytest-bdd steps, typed `ScenarioContext`, a reference slice, ratified constitution | the project tree; fingerprints in `.ekit/golden.lock.yaml` |

Stacks in MVP1: `fastapi-jinja` (with a golden landing zone), `fastapi-react`, `springboot-vanilla`,
`springboot-react`.

## Golden landing zone (0.3.0)

Models, smaller ones especially, produce different landing zones on different runs, loop on them,
and later "simplify" them during feature work. For `fastapi-jinja` the kit therefore ships the
landing zone itself (`kit/golden/fastapi-jinja/`, golden revision 1.0.0). `ekit init` installs it,
and `--baseline generate` opts out. Brownfield folders and the other stacks always generate.

- **Installed deterministically.** Files are copied with the project name rendered in, the
  constitution is ratified without a model (`ekit constitution ratify`), and `uv lock` runs once
  (it needs network access).
- **Core frozen.** `src/app/main.py`, `src/app/core/**`, `src/app/api/**`, `src/app/web/**`, the
  base templates, `tests/acceptance/conftest.py`, `tests/acceptance/support/**`, the `000-*`
  scenarios and the conformance record are denied to the agent's edit tools. The baseline and green
  gates fail if any of them differs from `.ekit/golden.lock.yaml` (`BASE-GOLDEN-INTACT`,
  `GREEN-GOLDEN-INTACT`). A person changes the core with `ekit baseline unfreeze --reason`, then
  `ekit baseline accept --reason`; both are audited.
- **Seams for features.** Each feature's code goes in its own package, printed by
  `ekit feature package <NNN-slug>` (e.g. `src/app/features/f003_chat/`). Routers go in
  `src/app/features/registry.py`, templates in `src/app/templates/features/<slug>/` and migrations
  in `migrations/versions/`.
- **Test glue that cannot break the 0.2.x way.** Shared steps live in the frozen conftest. Every step
  takes `ctx: ScenarioContext`, and `ctx.recall` of a value the scenario never set raises
  `MissingScenarioStateError`, which red rejects (`RED-STATE-TYPED`, `RED-CLEAN-FAILURE`).
- **A reference slice to copy.** `specs/000-reference-slice/` with its package and step module is
  one complete, green feature. Features copy its shape and never use it (`RED-NO-EXEMPLAR`). It is
  never mounted in production.
- **Upgrades merge.** A kit with a new golden revision is applied by `ekit upgrade` as a three-way
  merge onto your files. Conflicts keep their markers and block `ekit gate baseline` until a person
  resolves them and runs `ekit baseline accept`.

`ekit baseline status` shows the revision, freeze state, drift and seams. Design and the mapping
from each 0.2.x bug to its structural fix: `docs/design/0.3.0-golden-landing-zone.md`.

## Happy path first (0.7.0)

0.1.x to 0.6.x were found on one small app that never converged: the pipeline fixed no shape before the
first test was frozen, applied full rigor before anything was stable, and no gate asked whether a user could
actually use the planned features. 0.7.0 makes the opposite the default for a **new golden project**
(`ekit init` picks `--lane happy-path`; `--lane classic` keeps the 0.6.4 flow). Design note:
`docs/design/0.7.0-happy-path-first.md`.

| # | Stage | Command | Gate | Rigor |
|---|---|---|---|---|
| 1 | Intake: BRD, PRD, questions **and `happy-path.md`** (key features, cross-feature journeys) | `/speckit.esdlc.brd` | `intake` (`INTAKE-HAPPY-PATH`: every key feature is in a journey) | as today |
| 2 | **Design**: `docs/design/architecture.md` + `design.yaml` (topology, ports, features -> operations/pages, seams, slices, decisions) | `/speckit.esdlc.design`, then a person: `ekit design approve --by` | `design` (`DESIGN-*`) | person approves |
| 3 | **W0 happy path**: build slice `S0` against the Day-0 seams; Gherkin **journeys** through the HTTP API | `/speckit.esdlc.slice S0`, `ekit run journeys` | `smoke` | `skeleton` |
| 4 | **Adoption point** | a person: `ekit wave advance --by` | design approved, `smoke` passes, baseline recorded; W0 journeys fingerprinted | -> `standard` |
| 5 | W1..n: changes, spec, red, green as in 0.6.4 | `/speckit.esdlc.change`, `/speckit.specify` | all existing gates (`SMOKE-W0-INTACT` keeps the happy path green) | `standard` |
| 6 | Enterprise overlay waves: real controls replace the dummies | | + `GREEN-NO-DUMMY` | `enterprise` |

- **Rigor is a property of the wave.** `policy/rigor.policy.yaml` says which checks run at `skeleton`,
  `standard` and `enterprise`; each wave in `.ekit/waves.yaml` names its `rigor:` (W0 `skeleton`, W1+ `standard`).
  Every gate report names the level and lists the checks it skipped because of it. No wave plan, or a wave
  without `rigor:`, means nothing changes: gates behave exactly as in 0.6.4. Raising rigor is a person action
  (`wave advance`).
- **The design gate.** `DESIGN-FILES`, `-SECTIONS`, `-SCHEMA`, `-PORTS`, `-SEAMS`, `-FEATURES` (every key FEAT has
  an operation or page and is in exactly one slice), `-BRS-LISTED`, `-DECISIONS`, `-JOURNEYS`, `-APPROVED`.
  `ekit design init [--from-code]` writes the templates (or drafts `design.yaml` from `Protocol` classes, the PRD
  and `reports/openapi.json`); `ekit design approve --by` is person-only (denied to the agent's shell).
- **Day-0 seams in the golden core (`fastapi-jinja` 1.1.0).** `get_principal()` with `DevUserProvider` (fixed users
  in `config/dev-users.yaml`, HTTP Basic for the API, a minimal `/signin` form and session cookie for pages; refuses
  unless `APP_ENV` is `dev` or `test`), `AuditSink` + `LogAuditSink`, an `X-Request-Id` middleware, settings from
  env, and the `owner_id` data-owner convention. A **generic API step library** (`tests/acceptance/api_steps.py`:
  sign in as a dev user, call by `operation_id` resolved from the app's OpenAPI, remember / recall values, response
  assertions) means most journeys need no step code. A test-only middleware writes `reports/journeys.json` (and
  `reports/openapi.json`).
- **Traceability instead of sign-off.** `smoke` checks `SMOKE-JOURNEYS-PASS`, `-OPERATION-EXISTS`,
  `-OPERATION-EXERCISED` (a 2xx from a journey), `-PAGE-REACHABLE`, `-FEATURE-COVERED`, `-W0-INTACT`, plus
  `DESIGN-PORTS-IMPLEMENTED` (AST scan: Protocol with the declared methods, its dependency function, an adapter,
  a fake) and `BASE-SEAMS-PRESENT`. `ekit trace matrix [--format md|csv|json]` prints **BR -> FEAT ->
  operation/page -> journey -> last result**; `ekit trace postman` exports a Postman v2.1 collection (OpenAPI +
  journeys, HTTP Basic dev-user preset) for hand checks. `GREEN-NO-DUMMY` (enterprise rigor only) fails while the
  dummy principal or audit sink is still declared in `design.yaml` or set for a non-dev environment file.

Known limits: the golden application code is verified statically and with stubbed framework modules in this
repository, not run (FastAPI and pytest-bdd are not ekit dependencies); journeys prove a feature was *called
successfully*, not that every assertion is meaningful; UI-only features are covered by reachability only; the
generic steps and seams exist for the golden core only (other stacks get the design stage, rigor and the matrix).

## Brownfield: bug fixes and changes from the prompt (0.5.0)

On an existing system most work is not a BRD; it is one request. `/speckit.esdlc.change` takes it as
typed, with no file to create or pass:

```
/speckit.esdlc.change bug: after I open a chat the unread badge still shows 3 ticket=JIRA-482
/speckit.esdlc.change add a "mark all as read" button to the conversation list
/speckit.esdlc.change enhancement: unread badge should cap at 99+ affects=003
```

The agent classifies the request (`bug`, `enhancement` or `feature`; a prefix decides it), runs
`ekit change candidates "<text>"` to find the existing features it touches (word overlap with their
specs and scenarios, so it reads two specs rather than all of them), and runs `ekit change new`. That
allocates `CR-NNNN` and creates a **change request**: a small PRD folder
`docs/requirements/cr-NNNN-<slug>/` with

- `request.md`: the request **verbatim**, never edited afterwards;
- `change.yaml`: type, title, ticket, who recorded it, affected features, the scenarios it supersedes and,
  for a bug, `observed` / `expected` / `reproduction`;
- `brd.md`, `prd.md` (normally one `FEAT-01`) and `open-questions.yaml`, from the usual templates.

`ekit gate intake --prd CR-NNNN` checks it (`INTAKE-CHANGE-VALID`), then `/speckit.specify CR-NNNN`
creates the spec folder (`008-cr0007-unread-badge`), and the feature runs through the **same cycle and
gates as any other**: Gherkin → plan → tasks → red → commit → implement → green. `--prd CR-0007` works
wherever a PRD folder is accepted. `/speckit.specify` given plain free text now points to
`/speckit.esdlc.change` instead of creating an untraced spec.

### Red and green for a change

| Type | What red proves | Production code at red | Green |
|---|---|---|---|
| `bug` | the new scenario **reproduces** the defect: it fails on an assertion that shows the observed behaviour | **untouched and committed**: no stubs, no partial fix (`RED-BUG-REPRODUCED`) | the fix, with every other scenario still green |
| `enhancement` | new scenarios fail | 501 stubs for new routes; golden: in the **affected** feature's package | the change; superseded scenarios retired first |
| `feature` | as for any feature | 501 stubs, own package | as for any feature |

A bug's red is stronger evidence than a feature's: the failing test ran against exactly the code in
production. `RED-BUG-REPRODUCED` fails red if any file under the production source directories differs
from HEAD, or if a scenario fails with a 501 or `NotImplementedError`.

### When a change makes a delivered scenario wrong

A delivered feature's scenarios are frozen and assert the old behaviour, so green (which runs the whole
suite) could never pass. The CR lists those scenarios under `supersedes:`; before green **a person**
removes them from the delivered `.feature` file and runs

```
ekit change retire 003-chat SCN-003-04 --by CR-0007 --reason "CR-0007: badge now clears on open"
```

It checks that only the named scenarios were removed and every other line of the feature is unchanged,
then writes a `rebase` entry (who, when, CR, reason, new fingerprints) to that feature's ledger and
re-freezes it. The delivered feature's own gates judge against the rebased fingerprints from then on.
`GREEN-CHANGE-SUPERSEDED` fails the CR's green until this is done. The agent cannot run `retire`.

`ekit change list` (and a section in `ekit status`) shows every CR with its phase and spec folder.
Design and limits (refactors have no honest red; with waves on, a CR's ACs are placed in a wave like any
BRD's): `docs/design/0.5.0-change-lane.md`.

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
| git | `--source git+https://git.example.com/eng/sdd-kit.git@v0.3.0` | teams; pin a tag |

You can also set `EKIT_KIT_SOURCE`. Whatever the source, the kit is **copied into
`.ekit/kit` and pinned** in `.ekit/kit.lock.yaml` (source, tag, commit, sha256). Commit both:
everyone and every CI run then uses identical rules. `ekit doctor` detects local edits to the
vendored kit; `ekit upgrade [--source …]` re-fetches, re-pins and re-applies.

### What is pinned, and what is not

| Part | Where it lives | Pinned by | Changes when |
|---|---|---|---|
| **Rules**: gate policy, NFR catalogue, stack profiles, templates, agent rules | `.ekit/kit/` in the repository (committed) | `.ekit/kit.lock.yaml`: source, resolved commit, sha256 | someone runs `ekit upgrade` and commits the result |
| **Check engine**: the `ekit` CLI that reads those rules and judges the files (`checks.py`, `gates.py`, step scan, fingerprints) | each machine's uv tool folder | `ekit.version` in `.ekit/kit.lock.yaml` (since ekit 0.1.4), plus the kit's allowed range `requires.ekit` (e.g. `>=0.3.0,<0.4`) | a developer reinstalls the CLI |

Both parts decide a gate result. Identical rules judged by two different CLI versions can disagree,
because check logic changes between releases (0.1.1 changed how tags are read, 0.1.2 added
`RED-STEPS-ASSERT` and `GREEN-TESTS-UNCHANGED`, 0.1.5 stopped counting skipped scenarios as red, 0.2.1 added
`RED-STEPS-BOUND` and the committed-evidence checks). So:

- **One CLI version per project.** `ekit init` and `ekit upgrade` record the running CLI version in the lock.
  Everyone, and CI, installs exactly that version.
- **Install by tag.** Tag the kit repository with the CLI version (e.g. `v0.3.0`; one tag then fixes both the CLI
  and the kit it ships) and install it with `uv tool install --force git+https://…/sdd-kit.git@v0.3.0`.
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
| 0 | `/speckit.constitution` | constitution seeded with fixed principles I–VIII (golden: already ratified by `ekit init`; use it for principles IX+) | — |
| 1 | `/speckit.esdlc.baseline` | landing-zone skeleton (greenfield), gap assessment (brownfield), or — golden — install check and gate only; `docs/engineering/baseline-conformance.md` | `baseline` |
| 2 | `/speckit.esdlc.brd <file>` | `docs/requirements/<slug>/brd.md` (BR-###), `prd.md` (FEAT-##, AC-###), `open-questions.yaml` | `intake` |
| 2′ | `/speckit.esdlc.change <request>` (0.5.0, instead of 2 for one bug fix or change) | `docs/requirements/cr-NNNN-<slug>/`: `request.md` (verbatim), `change.yaml`, small `brd.md` / `prd.md` / `open-questions.yaml` | `intake` |
| 3 | `/speckit.esdlc.questions` | answers recorded, PRD updated | `ready` |
| 4 | `/speckit.specify FEAT-01` (or `CR-NNNN`) | `spec.md` + `trace.yaml` | `ready` (before), `spec` (after) |
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

- **intake**: files exist; BR ids present; AC ids unique; every BR cited by an AC or listed out of scope; question register valid; change requests (0.5.0): `change.yaml` complete, request kept verbatim, affected features and superseded scenarios exist, a bug states observed and expected behaviour (`INTAKE-CHANGE-VALID`).
- **ready**: no open/deferred blocking question; every answered blocking question names `answered_by`; no `[TBD…]` / `[NEEDS CLARIFICATION` in the PRD; no `[TBD` left in a bug's facts (`READY-CHANGE`).
- **spec**: `trace.yaml` valid and points at real ACs; every AC referenced in `spec.md`; no clarification markers; with an approved wave plan, every AC is in the current or an earlier wave (`SPEC-WAVE-SCOPE`).
- **scenarios**: `.feature` files parse; each scenario has exactly one `@SCN-<feature>-nn`, unique repo-wide; every AC is tagged on ≥1 scenario.
- **plan**: ADR numbers unique; every applicable **feature-scope** NFR has a row `Addressed | N/A | Waived`; evidence/justification present; `Waived` cites an ADR (`ADR-0007` or `docs/adr/0007-….md`; a date is not an ADR reference); with an approved wave plan, `Deferred (W2)` for an NFR the plan defers until W2.
- **baseline**: same for **platform-scope** NFRs in `baseline-conformance.md`; profile `required_paths` exist; **ENV-01** environment isolation (below); ADR numbers unique; lint runs; principles I–VIII of the constitution match the kit template (`BASE-CONSTITUTION`, since 0.3.0; unratified is a warning); golden projects: the core matches `.ekit/golden.lock.yaml` (`BASE-GOLDEN-INTACT`). A pass is recorded in `.ekit/ledger/baseline.yaml`, which `ekit status` shows as passed, stale (conformance record, kit or active profiles changed since) or not run.
- **red**: first scans the step modules (pytest-bdd). Golden projects also: scenario state on `ScenarioContext`, never a shared dict (`RED-STATE-TYPED`); the feature neither is nor uses the reference slice (`RED-NO-EXEMPLAR`). `RED-STEPS-ASSERT`: a step whose body is `pass`, `...`, a docstring or `assert True` is an error, as is an absolute path in `scenarios()`. `RED-STEPS-BOUND`: every step of every scenario (Background included, outlines expanded) has a definition the binding module can see, with the right keyword type; a scenario that fails at an early step would otherwise hide a later step with no definition. Then runs the acceptance suite(s); every scenario of the feature appears in the Cucumber-JSON report and **fails** (a scenario that passes before implementation is an error; undefined, pending, ambiguous or **skipped** scenarios are errors, because only an observed failure proves the test can fail). Bug change requests (0.5.0): production source untouched since HEAD and no scenario failing on a 501 / `NotImplementedError` (`RED-BUG-REPRODUCED`); scenarios a change supersedes but nobody retired yet are a warning (`RED-CHANGE-SUPERSEDES`). Writes `.ekit/ledger/<feature>.yaml` with git HEAD and a sha256 fingerprint of the feature files and the test modules bound to them.
- **red-recorded** and **green**: the files fingerprinted at red, and the ledger, are committed exactly as recorded (`REDREC-COMMITTED`, `GREEN-RED-COMMITTED`).
- **green**: change requests: every scenario the change supersedes has been retired by a person (`GREEN-CHANGE-SUPERSEDED`); golden projects: the core and shared test helpers are unchanged (`GREEN-GOLDEN-INTACT`) and the reference slice is not used (`GREEN-NO-EXEMPLAR`); red was recorded first for every scenario (a ledger status of `failed`); every step is bound (`GREEN-STEPS-BOUND`, for features recorded red before 0.2.1); the feature files and bound test modules are unchanged since red (`GREEN-TESTS-UNCHANGED`); all scenarios pass and the suites exit 0 (no regressions); unit, lint, coverage pass; SCA and unchecked tasks warn.

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

Red proves a test *fails*, not that it is *good*. Three deterministic guards close that gap:

- **`RED-STEPS-ASSERT`** rejects steps that cannot fail. A `Then` whose body is `pass` lets a scenario go
  green with the wrong behaviour, because the scenario was only red for an earlier reason. A deliberate
  no-op is allowed with `# ekit: allow-empty-step <reason>` on the step, so the exception shows up in review.
  The scan is implemented for pytest-bdd; for Cucumber-JVM and cucumber-js the gate prints an info line and
  step bodies must be reviewed by hand.
- **`RED-STEPS-BOUND`** rejects steps that have no definition the binding module can see (missing, defined
  under another keyword type, or in a module that is not imported). Without it, a scenario that fails at an
  early step hides a later step that can never run, and the frozen test can never pass. pytest-bdd only.
- **`GREEN-TESTS-UNCHANGED`** compares the files recorded at red with the files now. Editing a recorded test
  to get green fails the gate. Covered: the feature's `.feature` files and the test modules that name them or
  their `@SCN-<NNN>-` ids. Not covered: shared helpers and `conftest.py`. In golden projects (0.3.0) those are
  part of the frozen core and `GREEN-GOLDEN-INTACT` covers them; elsewhere, review changes to them.
- **`RED-CLEAN-FAILURE`** (since 0.2.2) rejects a scenario that *errored* — a `KeyError` reading state no step
  set, a step binding mismatch, a typo — rather than failed on a genuine assertion. pytest-bdd reports both as
  plain `failed`, so without this check `RED-RUN` accepts either; a scenario can be frozen while its own test
  glue is broken, and the breakage only surfaces during implementation, well after it was cheap to fix. Default
  allow-list is `AssertionError`; add others (e.g. a deliberate `NotImplementedError` stub style) via the
  check's `allow:` param in policy, or the usual override if it's a one-off.

### Edit protection: the agent cannot touch frozen files

Detecting a change after the fact is not the same as preventing it. `ekit` therefore owns a set of
`permission.edit` deny rules in the project's `opencode.json`, which OpenCode enforces on the agent's
edit, write and patch tools:

| Rule | Set when | Lifted by |
|---|---|---|
| `.ekit/*`, `opencode.json`, `.opencode/*` | `ekit init`, `sync`, `upgrade` | never (humans edit these outside the agent) |
| `specs/<feature>/features/*` and the test modules bound to the feature | `ekit gate red` passes | `ekit unfreeze <feature> --reason "..."` |
| the feature's production source dir (profile's `layout.source`) | `ekit unfreeze` (since 0.2.2; default) | `ekit gate red` re-freezing, or `ekit unfreeze … --allow-src` to skip it |
| golden core (`golden.yaml` `frozen:`), 0.3.0 | `ekit init` (golden), `ekit baseline accept`, `ekit upgrade` | `ekit baseline unfreeze --reason "..."` (a person) |

The source-dir rule exists because unfreezing is for fixing the *test*: an agent that uses the window to
implement production code instead has, in effect, repeated the mistake the freeze exists to catch. It's
denied the moment `ekit unfreeze` runs and allowed again the moment the feature is re-frozen — `ekit status`
and `ekit doctor` both show it while active.

Since 0.2.0 ekit also owns `permission.bash` deny rules for the commands that record a person's decision:
`ekit unfreeze`, `ekit fix-red`, `ekit upgrade`, `ekit wave approve|advance|decline`, `ekit models …`, (0.3.0)
`ekit baseline unfreeze|accept|install`, (0.5.0) `ekit change retire` and (0.6.0) `ekit baseline enforce` and
`ekit constitution lock`. The
agent's shell tool cannot run them; it tells the user the command instead. Running them through another
wrapper (`uv run ekit …`, a script) is not covered, and the records they write name who acted.

### `ekit fix-red`: fixing a frozen test's own glue, in one reviewed step

A frozen test can fail at green not because the implementation is wrong but because the test's own glue is —
a step that assumed another scenario's setup already ran, a binding that doesn't match the feature text. Fixing
that means: unfreeze, get the production code back to how it looked when this was last genuinely red (so the
fix is proven against the same failure, not against code the test was never red against), run `ekit gate red`,
restore the production code, then a human reviews the test diff and commits. Doing this by hand means `git
stash` or a manual revert of files you may not fully remember editing — and `git stash` has nothing to grab once
the implementation is already committed, which is the common case by the time a frozen-test bug surfaces.

`ekit fix-red <feature> --reason "..."` automates the mechanical part only:

1. Requires the feature to be frozen and its production source dir(s) (profile's `layout.source`; in golden
   projects since 0.3.0, only the feature's own package, so other features' code is never reverted) to be clean
   (`git status --porcelain` empty) — it refuses rather than guess what of an uncommitted change is safe to move.
2. Unfreezes (narrow, as above) and temporarily checks the production source back to the commit recorded as
   this feature's last red (`.ekit/ledger/<feature>.yaml`), not via `git stash`.
3. Runs `ekit gate red` for the feature.
4. Restores the production source to exactly what it was before, whatever the outcome — including a file that
   didn't exist yet at the red commit (moved aside and back, not deleted).

It never commits anything: a clean result still means a human reviews the test diff and runs
`git add -A && git commit -m "test(...): red (...)"` themselves, same as every other red/green step in this
pipeline. It's denied to the agent's shell tool for the same reason `ekit unfreeze` is — this removes toil for
the person who already has to make the call, not a new thing an agent can decide to do on its own. If red still
isn't clean, the source is restored anyway and the message says to keep fixing the test and run it again.

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
the test either way. Since 0.2.1, `RED-STEPS-BOUND` finds such steps statically before the run; the pytest
output (`StepDefinitionNotFoundError`) remains the source of truth.

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
ekit status                 # PRDs, open questions, landing zone, per-feature gate state, waves, model routing
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
ekit baseline [status|drift]                     # golden landing zone (unfreeze / accept / install: a person)
ekit feature current [NAME] --for red|implement  # the one feature to work on, or an error listing the real ones
ekit feature package NNN-slug                    # golden: the feature's code package
ekit adr new "Title"                             # next free ADR number
ekit change new --type bug|enhancement|feature --title T --text "..." [--affects NNN] [--ticket ID]   # 0.5.0
ekit change list | show CR-0007 | show --feature NNN-slug | candidates "<request text>"
ekit change retire NNN-slug SCN-NNN-nn --by CR-0007 --reason "..."   # a person: retire a superseded scenario
ekit constitution ratify|check                   # fill placeholders deterministically / check I-VIII
ekit constitution lock                           # 0.6.0, a person, brownfield: adopt the team's own V-VIII (.ekit/constitution.lock.yaml)
ekit baseline enforce NFR-ID... --reason "..."    # 0.6.0, a person, brownfield ratchet (.ekit/baseline-enforced.yaml); no un-enforce
ekit init NAME --lane happy-path|classic          # 0.7.0: greenfield golden defaults to happy-path
ekit design init [--from-code] | status | approve --by "Name"   # 0.7.0 (approve: a person)
ekit gate design | smoke                          # 0.7.0
ekit run journeys                                 # 0.7.0: runs the journeys, writes reports/journeys.json + openapi.json
ekit trace matrix [--format md|csv|json]          # 0.7.0: BR -> FEAT -> operation/page -> journey -> last result
ekit trace postman [--out FILE]                   # 0.7.0: Postman v2.1 collection from OpenAPI + journeys
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
  policy/                 gate policy, wave policy, rigor policy, model routing policy
  extension/esdlc/        Spec Kit extension (commands + templates)
  preset/enterprise-baseline/  Spec Kit preset (template appends + command wraps)
  opencode/               AGENTS.md block + agents
  golden/<stack>/         golden landing zones (0.3.0): golden.yaml + tree/
tests/                    unit tests (pytest)
docs/design/              design notes per release
```

## Versions

| ekit | kit | Change |
|---|---|---|
| 0.1.1 | 0.1.2 | Cucumber JSON reader accepts tags with and without `@` (pytest-bdd writes them without). |
| 0.1.2 | 0.1.3 | `RED-STEPS-ASSERT`, `GREEN-TESTS-UNCHANGED`, clearer undefined-step messages, feature lookup in command text, agent rules to extend (never rewrite) the landing zone and not edit frozen tests. The kit declares `requires.ekit >= 0.1.2`; an older CLI refuses it. |
| 0.1.3 | 0.1.4 | Edit protection: ekit-managed `permission.edit` deny rules in `opencode.json`, `ekit freeze` / `unfreeze`, `frozen` column in `status`, doctor check. Requires `ekit >= 0.1.3`. |
| 0.1.4 | 0.1.5 | CLI version pinning: `kit.lock.yaml` records the CLI version (`ekit.version`); `doctor` fails on a mismatch, `status` and every gate report show it, `EKIT_REQUIRE_PINNED_CLI=1` makes gates refuse to run with another CLI; red/green ledger entries record `ekit_version`; `requires.ekit` accepts ranges (`>=0.1.4,<0.2`, also `>`, `<=`, `==`) and the kit declares an upper bound. Requires `ekit >=0.1.4,<0.2`. |
| 0.1.5 | 0.1.6 | Governance fixes found by validating the quiz against the code: `RED-RUN` rejects skipped scenarios and `ledger.red_first` counts only `failed` entries; `Waived` needs a real ADR reference (a date such as `2026-12` no longer satisfies it); overrides need `reason`, `approved_by` and `expires`; a blocking question answered without `answered_by` fails `ready` (and `intake`) and is refused by `questions import`. Requires `ekit >=0.1.5,<0.2`. |
| 0.2.0 | 0.2.0 | Optional **waves** (`ekit wave …`, `.ekit/waves.yaml`, AC-level scope, `SPEC-WAVE-SCOPE`, `Deferred (Wn)`, non-deferrable NFRs, inactive profiles skipped) and optional **model tiers** (`ekit models …`, red on flagship by default, frontmatter injection on sync, ledger records the configured model). Approval commands denied to the agent's shell tool. Both features are off unless configured. Requires `ekit >=0.2.0,<0.3`. Design: `docs/design/0.2.0-waves-and-model-tiers.md`. |
| 0.2.1 | 0.2.1 | Found on the first real project: `RED-STEPS-BOUND` / `GREEN-STEPS-BOUND` (pytest-bdd: every step has a visible definition of the right keyword type), `REDREC-COMMITTED` / `GREEN-RED-COMMITTED` (red evidence committed as recorded), `BASE-ADR-UNIQUE` / `PLAN-ADR-UNIQUE`, baseline pass recorded and shown in `ekit status` (with `000-*` smoke scenarios listed apart from features) and `ekit doctor`. Requires `ekit >=0.2.1,<0.3`. |
| 0.2.2 | 0.2.2 | Found fixing a 0.2.1-flagged bug on the same project: `RED-CLEAN-FAILURE` rejects a scenario that errored (broken test glue) rather than failed on an assertion, even though pytest-bdd reports both as `failed`; `ekit unfreeze` now denies the feature's production source dir by default while its tests are unfrozen (`--allow-src` to skip), re-allowed the moment it's re-frozen, so fixing a frozen test can't turn into unrelated implementation work. Command text and the AGENTS.md block both say step functions must be self-contained and that an unfreeze-fix touches only the named test file. Requires `ekit >=0.2.2,<0.3`. Design: `docs/design/0.2.2-clean-red-and-narrow-unfreeze.md`. |
| 0.2.3 | 0.2.3 | Found applying a 0.2.2-flagged fix by hand on the same project (a patch applied outside the agent's edit tool, caught correctly by `GREEN-TESTS-UNCHANGED`, then fixed with a manual unfreeze/revert/red/restore cycle): `ekit fix-red <feature> --reason "..."` automates that cycle — unfreeze, revert the feature's production source to its last-red commit (not `git stash`, which has nothing to grab once that source is already committed), run `ekit gate red`, restore the source either way — without ever committing. Denied to the agent's shell tool, same as `ekit unfreeze`. Requires `ekit >=0.2.3,<0.3`. Design: `docs/design/0.2.3-fix-red.md`. |
| 0.2.4 | 0.2.4 | Found running `ekit fix-red` on the same project: a run rejected by `RED-CLEAN-FAILURE` (an errored scenario, not a clean assertion failure) still recorded a red ledger entry and re-froze the feature, because `RED-RUN`'s own findings were already clean before `RED-CLEAN-FAILURE`, a later check in the same gate, got to reject the run — poisoning the ledger's "last red" reference for any later `fix-red` / `gate red` on that feature. The ledger write (and re-freeze) is now queued and only flushed once the whole gate has actually passed. `ekit fix-red`'s failure message also now explains the separate, structural limit that a non-assertion failure after a revert usually means the revert (which touches the feature's whole production source directory) reached back further than this fix needs, and suggests reverting just the specific file(s) by hand instead. Requires `ekit >=0.2.4,<0.3`. Design: `docs/design/0.2.4-defer-red-ledger-write.md`. |
| 0.5.0 | 0.5.0 | **Change requests from the prompt (brownfield).** `/speckit.esdlc.change <request>` takes a bug fix, enhancement or feature as typed: `ekit change new` allocates `CR-NNNN` and keeps the request verbatim in `docs/requirements/cr-NNNN-<slug>/` (`request.md`, `change.yaml`), a small PRD folder every existing gate works on; `--prd CR-0007` resolves everywhere. `ekit change candidates` ranks the existing features a request touches. Same red/green cycle; a bug's red must reproduce it against untouched committed code (`RED-BUG-REPRODUCED`, no 501 stubs). A change that makes a delivered frozen scenario wrong lists it under `supersedes:`; a person retires it with `ekit change retire` (ledger `rebase` entry, re-freeze; agent-denied) and `GREEN-CHANGE-SUPERSEDED` holds green until then. Golden: a bug fix or enhancement works in the affected feature's package (`ekit feature package`, `fix-red`). `/speckit.specify` given free text points to `.change`. Design: `docs/design/0.5.0-change-lane.md`. Requires `ekit >=0.5.0,<0.6`. |
| 0.5.1 | 0.5.1 | **Brownfield baseline.** New conformance status `Gap` (brownfield only, needs justification and a remediation ticket/task/ADR id; warns). `Waived` stays ADR-only and a person's decision. In a brownfield project (`mode: brownfield`) `BASE-SKELETON` missing paths warn instead of failing. Git warnings name the cause and fix (`dubious ownership`, not a repository, git missing); the missing runtime pin message shows the file format. Design: `docs/design/0.5.1-brownfield-baseline.md`. Requires `ekit >=0.5.1,<0.6`. |
| 0.6.0 | 0.6.0 | **Forward baseline (brownfield).** In an adopted repository the baseline applies to new code; existing code is accepted as-is. Day one needs only *pipeline readiness*: `layout.pipeline_paths` of each profile are errors if missing (additive files), other skeleton paths are not reported; git unusable is an error. `docs/engineering/baseline-conformance.md` is optional (`/speckit.esdlc.baseline snapshot`); new status `Inherited` (no evidence or ticket; info). Ratchet: `ekit baseline enforce NFR-ID --reason` (a person, one way) makes that NFR require Addressed / N/A / Waived+ADR. `ekit constitution lock` (a person) adopts the team's principles V-VIII; I-IV stay the kit's. Duplicate NFR rows are an error. Report folders are created before profile commands; a UTF-16 / BOM `.python-version` (PowerShell `>`) is reported with the fix. Feature plans in brownfield also cover platform NFRs for code they add or change. Design: `docs/design/0.6.0-forward-baseline.md`. Requires `ekit >=0.6.0,<0.7`. |
| 0.6.1 | 0.6.1 | Non-golden red guidance; `ekit feature package` no longer errors outside golden; agents stay inside the repository. Requires `ekit >=0.6.0,<0.7`. |
| 0.6.2 | 0.6.2 | Red gate warns on lint issues before freezing, so they are fixed before green instead of after. Requires `ekit >=0.6.0,<0.7`. |
| 0.6.3 | 0.6.3 | `GHERKIN-UI-ENTRY` (warn): a `@ui` scenario with no `Background` that acts on a page (sends/selects/submits/...) before it opens/navigates to one is flagged - each scenario runs from a fresh state, so acting without first entering is usually a missed step, not real coverage. Heuristic: a file-wide `Background` is assumed to supply entry steps for every scenario in it; false negatives are expected, false positives should be rare. Requires `ekit >=0.6.0,<0.7`. |
| 0.6.4 | 0.6.4 | `RED-STEPS-ASSERT` (`bdd.vacuous_steps`, warn) now also flags a `Given` step whose text describes an outage/failure (unavailable, outage, times out, unreachable, cannot be loaded/reached, fails to load/respond/connect/send) but whose body never wires a fault into the app (no `dependency_overrides`, `monkeypatch`, `mock.patch`/`Mock(`/`MagicMock(`/`patch(` found in its source) - a flag set with `ctx.remember(...)` alone has no effect on the request path. Deliberately narrower than business-rule-denial wording ("denied", "forbidden", "rejected", "invalid"), which is usually real and already enforced. A deliberate unwired fault step is allowed with `# ekit: allow-unwired-fault <reason>`. Requires `ekit >=0.6.0,<0.7`. |
| 0.7.1 | 0.7.1 | **Fixes from the first happy-path test run.** `SMOKE-RUN` fails (exit code and last output lines) when `ekit run journeys` exits non-zero; approving the design places the ACs of the W0 slices in W0 (who/when in `.ekit/waves.yaml`) and proposes the rest for W1; golden `fastapi-jinja` 1.1.1: empty `migrations/versions/0001_initial.py` (one revision per slice) and `db_schema` / `db_session` fixtures on a temp SQLite file; journey steps take typed args (`true`/`false`/numbers/`null`) and `the response does not contain`, `the call fails with status N`, `the list is empty`; optional `package:` per feature in `design.yaml` (`ekit feature package FEAT-nn`); a port may declare `adapter: in-process` (or be bound by its dependency function) so one class satisfies `DESIGN-PORTS-IMPLEMENTED`; `ekit init` ends "Done with warnings" when `uv lock` failed. Design: `docs/design/0.7.1-test-run-fixes.md`. Requires `ekit >=0.7.0,<0.8`. |
| 0.7.2 | 0.7.2 | **Fixes from the second test run.** Golden `fastapi-jinja` 1.1.2: `the response contains` / `does not contain` resolve `{name}` from remembered values, and an unknown `{name}` / `<name>` is an error instead of a vacuous pass; `ekit init` creates a missing target directory and runs `git init` + an initial commit (never into an existing repo: it prints the commit command); gates in the happy-path lane print an info line, not "wave plan no longer valid", before the design is approved; `DESIGN-DECISIONS` requires the cited ADR to mention the decision id or title, and `ekit adr new "Title" --decision D1` writes that reference. Design: `docs/design/0.7.2-test-run-fixes.md`. Requires `ekit >=0.7.0,<0.8`. |
| 0.7.0 | 0.7.0 | **Happy path first.** Greenfield golden projects default to the happy-path lane (`--lane classic` keeps 0.6.4): `happy-path.md` at intake (`INTAKE-HAPPY-PATH`), a **design stage** (`architecture.md` + `design.yaml`, gate `design` with `DESIGN-*`, `ekit design init [--from-code]` / `approve --by`), a **W0 slice** proved by Gherkin journeys and gate `smoke` (`SMOKE-JOURNEYS-PASS`, `-OPERATION-EXISTS`, `-OPERATION-EXERCISED`, `-PAGE-REACHABLE`, `-FEATURE-COVERED`, `-W0-INTACT`, `DESIGN-PORTS-IMPLEMENTED`, `BASE-SEAMS-PRESENT`), **rigor by wave** (`policy/rigor.policy.yaml`, `rigor:` per wave; reports name the level and the skipped checks), an adoption point on `wave advance` out of W0 (design approved, smoke green, baseline recorded, journeys fingerprinted), `GREEN-NO-DUMMY` (enterprise rigor), `ekit trace matrix` / `postman`. Golden `fastapi-jinja` 1.1.0: Day-0 seams (dev-user principal, audit sink, request id, data owner) and a generic API step library. New commands `/speckit.esdlc.design`, `/speckit.esdlc.slice`. Design: `docs/design/0.7.0-happy-path-first.md`. Requires `ekit >=0.7.0,<0.8`. |
| 0.4.1 | 0.4.1 | `GREEN-LINT` failed on Spec Kit's own scripts (`.specify/scripts/python/*.py`, E501) because the fastapi profile ran `ruff check .` over the whole repository. `lint` and `format` now pass `--extend-exclude .specify,.opencode,.ekit`, and the golden pyproject (revision 1.0.1) sets the same `extend-exclude`. Requires `ekit >=0.4.0,<0.5`. |
| 0.4.0 | 0.4.0 | **Split freeze and action log.** Found on the intranet messenger: step functions after the first failing step never run in red, so logic errors in them (a method that doesn't exist, the wrong object or return value) surfaced only in green, in a frozen module, and needed repeated person unfreezes. Red now type-checks the feature's test module (`RED-GLUE-TYPED`) and, in golden projects, rejects 404 failures where a 501 stub was expected (`RED-ROUTE-STUBBED`). `freeze.mode: split` (default for golden projects, `strict` otherwise; `.ekit/project.yaml`) keeps `.feature` files frozen but lets the agent fix step bodies; green checks the bindings (`GREEN-CONTRACT-INTACT`), `Then` assertions and hazards (`GREEN-GLUE-NOT-WEAKENED`), new conftest or step modules (`GREEN-NO-SHADOW-GLUE`), and re-runs amended tests against the red-time code, which must still fail cleanly (`GREEN-GLUE-STILL-RED`); the diff is recorded under `.ekit/evidence/`. `ekit freeze --recontract` for features recorded red before 0.4.0. `ekit blocked` (allowed to the agent). Append-only, hash-chained action log `.ekit/logs/actions.jsonl` for every `ekit` command and, through the OpenCode plugin `.opencode/plugin/ekit-audit.js`, every agent tool call; `ekit log tail\|show\|why\|export\|verify`. Requires `ekit >=0.4.0,<0.5`. Design: `docs/design/0.4.0-split-freeze-and-action-log.md`. |
| 0.3.0 | 0.3.0 | **Golden landing zone** for `fastapi-jinja` (revision 1.0.0) plus structural fixes for every 0.2.1–0.2.5 bug class. Typed `ScenarioContext` and a shared step library in a frozen conftest (`RED-STATE-TYPED`); the golden core and test helpers are frozen and fingerprinted (`BASE-`/`GREEN-GOLDEN-INTACT`); one package per feature, which `fix-red` reverts alone; `ekit feature current` replaces the model choosing the active feature, and no command text carries an example name; `RED-`/`GREEN-NO-EXEMPLAR`; `ekit adr new`; deterministic `ekit constitution ratify` and `BASE-CONSTITUTION`; three-way golden upgrades. `ekit init --baseline golden\|generate`. Requires `ekit >=0.3.0,<0.4`. Design: `docs/design/0.3.0-golden-landing-zone.md`. |
| 0.2.5 | 0.2.5 | Found mid-`/speckit.implement` on the same project: an agent treated the illustrative example in a command's "active feature" step (`001-user-admin`, `001`) as a real feature to fall back to when `$ARGUMENTS` was empty. `speckit.implement.md` and `speckit.esdlc.red.md` now say explicitly that those examples show only the *shape* of a feature name, name them, and say never to fall back to one — always run `ekit status` instead. Wording-only; no CLI change. Requires `ekit >=0.2.5,<0.3`. |

Upgrade: `uv tool install --reinstall ./enterprise-sdd-kit` (or `--force git+…@<tag>`), then in each project
`ekit upgrade` and commit `.ekit/`. Upgrading to 0.7.0: existing projects are unchanged (no `rigor:` means
`standard`; their `lane` is `classic`; `ekit gate all` does not run `design` / `smoke`). A golden project gets
revision 1.1.0 as a three-way merge (new core files for the seams and journey steps, small edits to `main.py`,
`settings.py`, `middleware.py`, `conftest.py`; resolve conflicts, then `ekit baseline accept`). To adopt the lane in an
existing project: set `lane: happy-path` in `.ekit/project.yaml`, give waves a `rigor:` (`ekit wave init --force` writes
W0/W1), `ekit design init --from-code`, and re-run `ekit sync` so `ekit design approve*` is denied to the agent's shell.
Upgrading to 0.7.1: no action for classic projects. A happy-path golden project gets golden 1.1.1 as a three-way merge
(new `migrations/versions/0001_initial.py`, `tests/conftest.py` now uses a temp SQLite file and adds `db_schema` /
`db_session`, `tests/acceptance/api_steps.py` gains the typed args and negative steps; then `ekit baseline accept`).
Re-approve the design (`ekit design approve --by`) to place the W0 scope in an existing empty wave plan.
Upgrading to 0.7.2: no action for classic projects. A happy-path golden project gets golden 1.1.2 (only
`tests/acceptance/api_steps.py` changes; `ekit baseline accept`). Accepted decisions in `design.yaml` whose ADR does not mention the
decision id or title now fail `DESIGN-DECISIONS`: add `Decision: D1` to the ADR (or recreate it with `ekit adr new --decision D1`).
Projects vendored before 0.1.4 have no CLI pin: `ekit doctor` says so until
`ekit upgrade` records one.

Moving to 0.1.5 can turn existing results red on purpose: overrides without `approved_by`/`expires` stop
applying, `Waived` rows that cite only a date fail, and a feature whose red ledger shows `skipped` instead of
`failed` must be taken back to red (`ekit unfreeze … --reason`, stubs, `ekit gate red`). Run `ekit gate all`
after `ekit upgrade` and fix what it reports in the same reviewed change.

Moving to 0.2.0 changes nothing for projects that use neither waves nor model tiers, except that
`opencode.json` gains the `permission.bash` deny rules (restart OpenCode after `ekit upgrade`).

Moving to 0.2.1 can turn results red on purpose: a feature whose red tests have an unbound step fails green
(take it back to red: `ekit unfreeze … --reason`, stubs, add the definition, `ekit gate red`); red evidence that
was never committed fails `red-recorded` and `green` until it is; duplicate ADR numbers fail `baseline` and `plan`.
Run `ekit gate baseline` once after upgrading so `ekit status` has a landing-zone record.

Moving to 0.2.2 can turn an existing red entry invalid: if a scenario was frozen while actually erroring (not
failing on an assertion), `RED-CLEAN-FAILURE` now rejects it on the next `ekit gate red` for that feature — take
it back to red the usual way and fix the test glue, not the production code. Nothing changes for a feature
whose red already failed cleanly.

Moving to 0.2.3 changes nothing by itself — `ekit fix-red` is a new, opt-in command (and a new
`permission.bash` deny rule for it; restart OpenCode after `ekit upgrade`). Use it instead of the manual
unfreeze/revert/red/restore cycle the next time a frozen test's own glue, not the implementation, is wrong.

Moving to 0.2.4 changes nothing for a project that has never had a red run rejected by `RED-CLEAN-FAILURE`
after `RED-RUN` itself passed. If one has: check `.ekit/ledger/<feature>.yaml` for an entry that doesn't
actually belong (recorded moments before a `RED-CLEAN-FAILURE` rejection in the same `ekit gate red` /
`ekit fix-red` run) and remove it by hand before trusting that feature's "last red" again.

Moving to 0.2.5 changes nothing — it's a wording fix to two command templates. If an agent has ever
picked `001-user-admin` (or any other obviously-not-real feature) as the active feature when you gave
it no `$ARGUMENTS`, that's the bug this fixes; nothing to do beyond upgrading.

Moving to 0.3.0 changes nothing for a project created before it apart from three things:
- `BASE-CONSTITUTION`: a constitution whose I–VIII were reworded now fails `ekit gate baseline`;
  restore them from the template.
- The red and implement commands ask `ekit feature current` instead of reading `ekit status`.
- `opencode.json` gains three `permission.bash` denies; restart OpenCode after `ekit upgrade`.

All golden checks are informational in non-golden projects. A greenfield project made before 0.3.0
with nothing in it yet can switch to golden with `ekit baseline install`. A project with code keeps
its generated landing zone.

## Status of MVP1

Verified against Spec Kit 1.2.7 (source build) on Linux: greenfield `init`, brownfield `adopt`,
kit from bundled / folder / git tag, extension + preset install, command wrapping and template
composition, constitution seeding, every gate pass/fail path, red→green ledger, CSV question
round-trip, overrides, tamper detection, upgrade. Exercised on macOS by a real user run with
FastAPI + pytest-bdd (which found the tag-format and empty-step gaps fixed in 0.1.1 and 0.1.2). Not yet
exercised: Windows hosts, the Spring Boot and React toolchains, and agent output quality on smaller models,
which can loop or rewrite baseline code; the gates catch it, they do not prevent it.

0.2.0 (waves, model tiers), 0.2.1 (step binding, committed evidence, landing-zone status), 0.2.2
(clean-failure check, narrow unfreeze), 0.2.3 (`ekit fix-red`), 0.2.4 (deferred ledger recording), 0.2.5
(active-feature wording) and 0.3.0 (golden landing zone, structural fixes) are covered by unit and CLI tests (0.2.5's are wording-presence checks; it can't
test agent comprehension, only that the kit's own text says the right thing). 0.2.1's gap (a scenario frozen
while actually erroring, not failing cleanly), 0.2.2's fix for it, 0.2.3's automation of the fix-it cycle it
created, 0.2.4's fix for a way *that* automation could itself poison the ledger, and 0.2.5's fix for an agent
falling back to a command template's own illustrative example were all found debugging the same real project
on 0.2.0, which is still the only version run end-to-end against a live Spec Kit + OpenCode install; 0.2.2
through 0.3.0 themselves have not. In generated (non-golden) projects `ekit fix-red` also has a known, undefended limit (golden projects since
0.3.0 revert only the feature's own package): reverting a feature's
whole production source directory to its last-red commit can reach back further than the fix needs on a
project with several features sharing that directory (it can strip out shared code added since, or an
earlier shape this feature's own later work changed) — the fix's own failure message explains the narrower
manual alternative. Confirm
on the first project you upgrade that Spec Kit writes its OpenCode commands to `.opencode/commands/`
(or `.opencode/command/`) and that `ekit models show` lists them without "(no file under .opencode/)".

0.5.0's change lane (`ekit change …`, the CR checks, ledger rebase after `retire`) is covered by unit and CLI
tests (`tests/test_ekit_050_change.py`) and has not yet run against a live Spec Kit + OpenCode install.
Confirm on the first project that Spec Kit registers `/speckit.esdlc.change` (`ekit sync` after upgrading)
and that a small model passes `--text` intact; if quoting breaks, the command tells it to paste the request
into `request.md` instead.

0.3.0's golden application (FastAPI, Jinja, pytest-bdd) passes its own `ruff check` and
`ruff format --check`. The kit's tests verify statically that it parses, that every step is bound,
that no step pattern shadows another, and that its conformance record passes. It has **not yet been
run**: the build environment had no FastAPI, no pytest-bdd and no network. On the first machine
with them, run `ekit init x --stack fastapi-jinja`, `ekit run install`, `ekit run unit`,
`ekit run acceptance`, `ekit run typecheck` and `ekit gate baseline`, and report failures as a
golden 1.0.1 fix.
