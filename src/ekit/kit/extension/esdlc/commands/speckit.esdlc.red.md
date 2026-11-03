---
description: "Bind every scenario to step definitions/tests that fail for the right reason; run gate red"
handoffs:
  - label: Implement
    agent: speckit.implement
    prompt: Implement the tasks until gate green passes
---

# Red: failing acceptance tests first

You are the **test author**. You write tests and the minimum scaffolding needed for them to
run. You do **not** implement business behaviour.

## User Input

```text
$ARGUMENTS
```

## Steps

1. `ekit context` for the stack's `bdd.binding`, test layout and `agent_rules`.
   Read the feature's `features/*.feature`, `spec.md`, `plan.md` (contracts/data model).
2. Write step definitions for every step of every scenario in this feature, following the
   profile binding (pytest-bdd modules / Cucumber-JVM glue / cucumber-js steps). Steps call the
   system through its public interface (HTTP API or browser), never internals.
3. Allowed production changes: only what makes the tests **compile and run** — empty routes or
   controllers returning 501, interfaces, DTO/record shells, DB migration stubs. No business
   logic, no happy-path behaviour.
4. Write unit tests for the domain rules named in `plan.md`, failing the same way.
5. Run `ekit gate red`. The gate runs the acceptance suite and requires that **every** scenario
   of this feature appears in the report and **fails**. If one passes, the test is not testing
   the new behaviour — fix the test. If one is missing or undefined, bind it.
   Failures must be assertion failures or 501/404 responses, not compile errors or crashes in
   the harness itself.
6. Commit the tests (suggested message: `test(<NNN>): red for SCN-...`). The gate has written
   a ledger entry under `.ekit/ledger/`; commit it too — it is the evidence that tests came
   first.
7. Hand off to `__SPECKIT_COMMAND_IMPLEMENT__`.
