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

- **Greenfield** (no application code yet): build the skeleton.
- **Brownfield** (application code exists): **assess, don't impose.** Do not restructure
  existing code. Produce the conformance record with honest statuses and turn every gap into
  either a remediation task or a Waived entry with an ADR.

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
4. Add `docs/adr/0001-record-architecture-decisions.md` and one ADR for the stack choice.

## Both modes

5. Write `docs/engineering/baseline-conformance.md` from `ekit template esdlc-conformance-template`:
   one row per platform-scope NFR that applies to this stack, status `Addressed` / `N/A` /
   `Waived`, and evidence (file path, config key or test). `N/A` and `Waived` need a
   justification; `Waived` also an ADR id.
6. Run `ekit gate baseline`. Fix errors and re-run until it passes. Then run each profile
   command (`ekit run lint`, `ekit run unit`, `ekit run acceptance`) and fix failures.
7. Report what was created or assessed, the waivers, and the next step
   (`__SPECKIT_COMMAND_ESDLC_BRD__` for the first BRD).
