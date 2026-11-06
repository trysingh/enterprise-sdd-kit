---
description: "Build or assess the engineering landing zone for the project's stack; run gate baseline"
---

# Engineering landing zone

Makes the repository satisfy the **platform-scope** NFRs of the engineering baseline once,
so feature work only has to deal with feature-scope NFRs.

## User Input

```text
$ARGUMENTS
```

## Context to load first

1. `ekit context` — prints the stack, its profiles (with `layout`, `commands`, `controls`,
   `agent_rules`) and the NFR catalogue filtered to this stack. Treat it as binding.
2. `.specify/memory/constitution.md`.
3. Existing code, if any (`git ls-files`).

## Mode

- **Golden** (`ekit baseline status` names a golden landing zone, installed by `ekit init`):
  the landing zone already exists and its core is frozen. **Do not generate or rewrite anything.**
  Only: run `ekit run install`, `ekit gate baseline`, `ekit run unit` and `ekit run acceptance`;
  report the results. If a gate fails, report the finding to the user — a failing golden core is a
  kit or environment problem (for example `uv.lock` not generated yet: the user runs `uv lock`), not
  something to fix by editing core files. Then go to step 7.
- **Greenfield** (no application code yet): build the skeleton.
- **Brownfield** (application code exists; `ekit` records `mode: brownfield`): the baseline
  applies **forward**. Existing code is accepted as-is; new features and change requests meet the
  constitution and the baseline for what they touch. The only day-one requirement is **pipeline
  readiness**: what the red and green gates need. **Never assess, restructure or edit existing
  code.** Steps:
  1. `ekit gate baseline`. Its errors list the missing pipeline paths (`layout.pipeline_paths` of
     each profile, for example `pyproject.toml`, `.python-version`, `tests/unit`,
     `tests/acceptance/conftest.py`, `.gitignore`). Add only those, and only the ones that are
     purely additive. Do not touch existing files. Write a pin file as plain text
     (`uv python pin 3.12`, not a PowerShell `>` redirect, which writes UTF-16).
  2. Commit them (the red/green evidence needs commits; git must work: see the gate's message
     if it does not).
  3. `ekit run install`, `ekit gate baseline`, `ekit run unit`, `ekit run acceptance`. Empty test
     suites are fine. Report what fails; do not fix existing code to make it pass.
  4. Skeleton paths outside the pipeline set are not required (the gate prints one info line).
     `docs/engineering/baseline-conformance.md` is **optional**. Write it only if the user's input
     contains the word `snapshot`: then add one row per platform-scope NFR with an honest status
     (`ekit template esdlc-conformance-template`). Use `Addressed` (evidence: file or config key)
     only for what you have seen met; `N/A` with a reason; **`Inherited`** for everything else,
     including anything you did not look at. `Inherited` needs no evidence and no ticket. **Never
     invent a ticket, task or ADR id.** Do not use `Waived` (a person's decision with an ADR) and
     do not use `Gap` unless the user gave you a real reference.
  5. Two PERSON actions you may recommend but never run (they are denied to your shell):
     `ekit baseline enforce <NFR-ID> --reason "..."` (the ratchet: from then on that NFR must be
     Addressed, N/A or Waived with an ADR; one way, no un-enforce) and `ekit constitution lock`
     (adopts the team's own principles V–VIII instead of the kit's). Tell the user the exact command.
  Then go to step 7.

## Greenfield steps

1. Create every path in each profile's `layout.required_paths`, under the stack root given by
   `ekit context`. Implement the profile `controls` for all platform-scope NFRs:
   settings, structured logging, correlation id, error model, health endpoints, security
   headers/CORS, auth wiring (configurable, disabled only via an explicit dev flag),
   Dockerfile (non-root), lockfiles.
2. Wire the BDD runner exactly as the profile's `bdd.binding` says, reading features from
   `specs/`. Add one smoke scenario at `specs/000-landing-zone/features/health.feature`
   tagged `@SCN-000-01` that checks the health endpoint and the correlation-id header, with
   its step definitions.
3. Make every profile `commands` entry runnable and non-interactive (scripts in package.json /
   plugins in pom.xml / tool config in pyproject.toml).
4. Add ADRs with `ekit adr new "Record architecture decisions"` and one for the stack choice
   (`ekit adr new` takes the next free number).

## Both modes

5. (Greenfield; brownfield only with `snapshot`, see above.) Write `docs/engineering/baseline-conformance.md` from
   `ekit template esdlc-conformance-template`:
   one row per platform-scope NFR that applies to this stack, status `Addressed` / `N/A` /
   `Inherited` and `Gap` (brownfield only) / `Waived`, and evidence (file path, config key or test). `N/A`,
   `Gap` and `Waived` need a justification. `Gap` also needs a remediation reference (ticket,
   task or ADR id) and only passes in a brownfield project, as a warning. `Waived` needs an
   ADR id and a person's approval; never mark a gap `Waived` yourself, use `Gap`.
6. Run `ekit gate baseline`. Fix errors and re-run until it passes. Then run each profile
   command (`ekit run lint`, `ekit run unit`, `ekit run acceptance`) and fix failures.
7. Report what was created or assessed, the gaps and waivers, and the next step
   (`__SPECKIT_COMMAND_ESDLC_BRD__` for the first BRD).
