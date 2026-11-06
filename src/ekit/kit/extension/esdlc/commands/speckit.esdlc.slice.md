---
description: "Build one slice of the approved design (W0 happy path): ports, services, operations and Gherkin journeys, no spec/plan/freeze; run gate smoke"
handoffs:
  - label: Adopt (leave W0)
    agent: speckit.esdlc.change
    prompt: Plan the first change after the happy path
---

# Slice (stage 3, wave W0, rigor `skeleton`)

You build one slice of `docs/design/design.yaml` as a thin but working app against the simulated
Day-0 seams. No spec, plan, tasks, red ledger or freeze in W0: the journeys are the proof.

## User Input

```text
$ARGUMENTS
```

A slice id, e.g. `S0`. Empty: ask which slice and stop.

## Preconditions

`ekit gate design` passes (design approved; this also placed the W0 scope from the slices), `ekit wave status --brief` shows the W0 wave. If not,
stop and say what is missing. Golden core files are frozen; do not edit them.

## Steps

1. Read the slice in `design.yaml` (features, journeys) and `happy-path.md`. Run
   `ekit context` for the stack rules.
2. **Per feature** (one package per `FEAT-` unless `design.yaml` groups features under a `package:` key;
   `ekit feature package FEAT-nn` prints it; features sharing a `package:` share one package; migrations: one
   revision per slice in `migrations/versions/`, tests use the `db_schema` / `db_session` fixtures, see
   `migrations/versions/0001_initial.py`):
   - each port as a `Protocol`, one adapter, one in-memory fake (named `InMemory...`);
   - services take ports through the dependency named in `design.yaml`;
   - every operation of the feature exists with exactly that FastAPI `operation_id`; every page
     exists; each table has the `owner_id` column; use `get_principal` and `AuditSink`, never read
     headers or `os.environ` directly;
   - unit tests for services using the fakes.
3. **Journeys** in `tests/acceptance/journeys/<j-id>-<slug>.feature`, tagged `@J-01 @FEAT-01 ...`
   (all features the journey touches). Use the generic API steps first (`Given I am signed in as`,
   `When I call "<operation_id>" ...`, `I remember`, `Then the call succeeds`); see
   `tests/acceptance/api_steps.py`. Use Scenario Outlines with 2-3 users/data rows. Write a
   feature-specific step only for pages or assertions the library cannot express, and it must
   assert something. `the response (does not) contain "{name}"` uses a remembered value; an unknown `{name}`/`<name>` is an error.
4. Run `ekit run unit`, then the journeys: `ekit run journeys` (writes `reports/journeys.json` and
   `reports/openapi.json`). Fix until they pass.
5. Run `ekit gate smoke`. Fix every error (missing operation, never-called operation, unreachable
   page, key feature without a journey, missing port method).
6. Commit. Report: the trace matrix (`ekit trace matrix`) and what remains for later waves. A
   person leaves W0 with `ekit wave advance --by "<name>"`; you never run it.

## Rules

- Happy path only: no error or edge handling yet. Do not add real auth, logging or security work.
- Do not change `design.yaml` to make a check pass; if the design is wrong, say so and stop.
