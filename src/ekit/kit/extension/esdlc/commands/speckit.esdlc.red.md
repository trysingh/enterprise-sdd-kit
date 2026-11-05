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

If `$ARGUMENTS` actually names a feature — a folder name (shape: `NNN-slug`) or just its number
(shape: `NNN`) — use that one. `001-user-admin` and `001` above are only examples of that *shape*,
not real features in this project; never treat them as the feature to implement just because
`$ARGUMENTS` is empty or unclear. If `$ARGUMENTS` names nothing real, run `ekit status` yourself
and take the one feature whose `scen` column is `ok` and `red` is `--`; if several qualify, ask
once which; if none do, say so and stop. Do not guess, and never fall back to an example name.

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
   Every step of every scenario needs a definition the binding module can see (itself, a `conftest.py`, or a module
   it imports), with the right keyword type: the gate checks this statically (`RED-STEPS-BOUND`), because a scenario
   that fails at an early step would otherwise hide a later step that has no definition at all.
   Each step function must be **self-contained**: never assume shared state (a dict key, a fixture value) was set
   by a step that belongs to a *different* scenario. Two scenarios that read almost the same, with one skipping a
   setup step the other has, are not interchangeable — the shorter one must set up what it needs itself. This is
   the single most common way a frozen test turns out to be broken rather than genuinely red.
3. Allowed production changes: only what makes the tests **compile and run** — empty routes or
   controllers returning 501, interfaces, DTO/record shells, DB migration stubs. No business
   logic, no happy-path behaviour.
4. Write unit tests for the domain rules named in `plan.md`, failing the same way.
5. Run `ekit gate red`. The gate runs the acceptance suite and requires that **every** scenario
   of this feature appears in the report and **fails**. If one passes, the test is not testing
   the new behaviour — fix the test. If one is missing or undefined, bind it.
   Failures must be assertion failures or 501/404 responses, not compile errors or crashes in
   the harness itself (the gate checks this too, `RED-CLEAN-FAILURE`: a `KeyError` or similar from
   broken test glue is rejected even though the scenario did technically fail).
   If you were asked to come back and fix a specific frozen scenario after `ekit unfreeze` (rather
   than writing red for the first time), edit **only** the test file(s) named for that fix in this
   turn — no production code, no unrelated tasks, even ones still open on the task list. Mixing in
   other work here is exactly how a "fix the test" commit ends up not fixing the test.
6. When the gate passes, `ekit` freezes the feature files and bound tests against agent edits (`opencode.json`
   deny rules). Tell the user: restart OpenCode before the next step so the freeze is applied. A wrong test
   is lifted only by the user with `ekit unfreeze <feature> --reason "..."`.
7. Tell the user to commit now, before any implementation: the `.feature` files, the tests, `.ekit/ledger/`,
   `.ekit/freeze.yaml` and `opencode.json` (suggested message: `test(<NNN>): red for SCN-...`). The ledger is the
   evidence that tests came first, and `ekit gate red-recorded` / `green` fail (`REDREC-COMMITTED`) until the files
   recorded at red are committed exactly as recorded.
8. Hand off to `__SPECKIT_COMMAND_IMPLEMENT__`.
