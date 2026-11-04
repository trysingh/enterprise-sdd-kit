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

## Active feature

Use the feature named in `$ARGUMENTS` (`001-user-admin`, `001`). If none is named, run `ekit status`
and take the one feature whose `scen` column is `ok` and `red` is `--`; if several qualify, ask once which.

## Steps

1. `ekit context` for the stack's `bdd.binding`, test layout and `agent_rules`.
   Read the feature's `features/*.feature`, `spec.md`, `plan.md` (contracts/data model).
2. Write step definitions for every step of every scenario in this feature, following the
   profile binding (pytest-bdd modules / Cucumber-JVM glue / cucumber-js steps). Steps call the
   system through its public interface (HTTP API or browser), never internals.
   Every step must set up state (`Given`), act (`When`) or assert observable behaviour (`Then`).
   A body of `pass`, `...` or a comment is rejected by the gate (`RED-STEPS-ASSERT`): a `Then` that cannot fail
   lets the scenario go green with the wrong behaviour. Build feature paths from the test file's own location,
   never absolute paths.
3. Allowed production changes: only what makes the tests **compile and run** — empty routes or
   controllers returning 501, interfaces, DTO/record shells, DB migration stubs. No business
   logic, no happy-path behaviour.
4. Write unit tests for the domain rules named in `plan.md`, failing the same way.
5. Run `ekit gate red`. The gate runs the acceptance suite and requires that **every** scenario
   of this feature appears in the report and **fails**. If one passes, the test is not testing
   the new behaviour — fix the test. If one is missing or undefined, bind it.
   Failures must be assertion failures or 501/404 responses, not compile errors or crashes in
   the harness itself.
6. When the gate passes, `ekit` freezes the feature files and bound tests against agent edits (`opencode.json`
   deny rules). Tell the user: restart OpenCode before the next step so the freeze is applied. A wrong test
   is lifted only by the user with `ekit unfreeze <feature> --reason "..."`.
7. Commit the tests (suggested message: `test(<NNN>): red for SCN-...`). The gate has written
   a ledger entry under `.ekit/ledger/`; commit it too — it is the evidence that tests came
   first.
8. Hand off to `__SPECKIT_COMMAND_IMPLEMENT__`.
