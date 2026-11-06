---
description: "Generate tagged Gherkin scenarios from the spec's acceptance criteria; run gate scenarios"
handoffs:
  - label: Plan
    agent: speckit.plan
    prompt: Create the implementation plan
---

# Spec → Gherkin

Executable acceptance criteria. Scenarios describe **behaviour** in business language; they
are the contract the red and green gates enforce.

## User Input

```text
$ARGUMENTS
```

## Steps

1. Locate the active feature directory (`specs/<NNN-name>/`): the one named in the input; otherwise run
   `ekit status` and take the feature whose `spec` column is `ok` and `scen` is `--` (ask once if several). Read `spec.md` and `trace.yaml`. If `trace.yaml` is missing, stop and tell the user
   to run `ekit gate spec` (the specify step creates it).
2. Write one or more `.feature` files in `specs/<NNN-name>/features/`, one per user story.
3. Tagging (parsed by the gate — be exact):
   - Every scenario gets exactly one unique id tag `@SCN-<NNN>-<nn>`, where `<NNN>` is the
     feature number (e.g. `@SCN-003-01`).
   - Every scenario gets the `@AC-xxx` tag(s) it proves. Every AC listed in `trace.yaml` must
     appear on at least one scenario.
   - Add `@ui` for scenarios that need a browser; leave it off for API/service-level ones.
   - Add `@nfr-<ID>` where a scenario proves a baseline NFR (e.g. `@nfr-SEC-02` for a
     forbidden-access scenario, `@nfr-OBS-05` for an audit-event scenario).
4. Style: declarative (what, not how-to-click), one behaviour per scenario, concrete example
   data, `Scenario Outline` + `Examples` for rule tables. Cover the negative paths the spec and
   baseline imply: validation failure (SEC-03), forbidden (SEC-02), audit event (OBS-05).
   No UI selectors, no SQL, no implementation detail. Before running the gate, re-read each
   scenario's own Given/When steps in isolation — no credit for what a sibling scenario set up;
   each scenario runs from a fresh state — and confirm every precondition its Then needs is
   actually present in that scenario, not assumed from the one above it. `GHERKIN-UI-ENTRY`
   catches the common case of this (a `@ui` scenario that acts on a page with no preceding
   open/navigate step and no `Background`), but it's a heuristic, not a guarantee.
5. Run `ekit gate scenarios`. Fix and re-run until it passes.
6. Report the scenario count per AC and the next step (`__SPECKIT_COMMAND_PLAN__`).
