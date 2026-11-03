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

Blocking questions that are open **or deferred** stop `/speckit.specify` for that PRD.

### What the gates actually check

- **intake**: files exist; BR ids present; AC ids unique; every BR cited by an AC or listed out of scope; question register valid.
- **ready**: no open/deferred blocking question; no `[TBD…]` / `[NEEDS CLARIFICATION` in the PRD.
- **spec**: `trace.yaml` valid and points at real ACs; every AC referenced in `spec.md`; no clarification markers.
- **scenarios**: `.feature` files parse; each scenario has exactly one `@SCN-<feature>-nn`, unique repo-wide; every AC is tagged on ≥1 scenario.
- **plan**: every applicable **feature-scope** NFR has a row `Addressed | N/A | Waived`; evidence/justification present; `Waived` cites an ADR.
- **baseline**: same for **platform-scope** NFRs in `baseline-conformance.md`; profile `required_paths` exist; **ENV-01** environment isolation (below); lint runs.
- **red**: runs the acceptance suite(s); every scenario of the feature appears in the Cucumber-JSON report and **fails** (a scenario that passes before implementation is an error; undefined steps are an error). Writes `.ekit/ledger/<feature>.yaml` with git HEAD.
- **green**: red was recorded first for every scenario; all scenarios pass and the suites exit 0 (no regressions); unit, lint, coverage pass; SCA and unchecked tasks warn.

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

Overrides without a `reason` or past `expires` are ignored and reported.

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

## Useful commands

```
ekit status                 # PRDs, open questions, per-feature gate state
ekit context [--nfr feature|platform] [--json]   # what agents read: stack, rules, NFRs + how
ekit run lint|unit|acceptance|coverage|sca       # same command on every OS
ekit gate all
ekit sync                   # re-apply pinned kit (after editing nothing but wanting a refresh)
ekit upgrade --source git+https://…@v0.3.0
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
src/ekit/                 CLI (gates, checks, kit source, installer, questions)
src/ekit/kit/             the kit itself (this is what gets vendored into projects)
  kit.yaml                manifest: stacks, components, version
  baseline/               NFR catalogue
  profiles/               stack profiles
  policy/                 gate policy
  extension/esdlc/        Spec Kit extension (commands + templates)
  preset/enterprise-baseline/  Spec Kit preset (template appends + command wraps)
  opencode/               AGENTS.md block + agents
tests/                    unit tests (pytest)
```

## Status of MVP1

Verified against Spec Kit 1.2.7 (source build) on Linux: greenfield `init`, brownfield `adopt`,
kit from bundled / folder / git tag, extension + preset install, command wrapping and template
composition, constitution seeding, every gate pass/fail path, red→green ledger, CSV question
round-trip, overrides, tamper detection, upgrade. Not yet exercised: Windows hosts, the real
FastAPI / Spring Boot / React toolchains (the landing-zone skeleton is generated by
`/speckit.esdlc.baseline` per profile), and OpenCode's runtime behaviour with the commands.
