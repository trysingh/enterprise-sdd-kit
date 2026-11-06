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

Run `ekit feature current --for red "$ARGUMENTS"` and use exactly the folder name it prints.
If it exits with an error, show the user its message (it lists the real features) and stop;
do not choose a feature yourself.

## Change requests (0.5.0)

Run `ekit change show --feature <feature>`. If it prints `none`, ignore this section.
- **bug**: you reproduce the bug against the code as committed. Write **tests only**: no stubs, no
  `not_implemented()`, no change under the production source, not even a partial fix. Each scenario
  must fail on an assertion that shows the *observed* (wrong) behaviour from `change.yaml`, through
  the existing routes or pages. Step 3 below does not apply. `RED-BUG-REPRODUCED` fails the gate on a
  501, a `NotImplementedError` or any uncommitted change to production source. If a scenario passes,
  either the bug is not where the change request says, or the scenario does not exercise it: say so to
  the user, do not weaken or bend the scenario.
- **enhancement**: as below, but new routes are stubbed in the package(s) `ekit feature package <feature>`
  prints (the affected feature's own package in golden projects), registered next to its existing ones.
  Do not touch existing behaviour; existing scenarios must stay green.
- **feature**: exactly as below.

## Steps

1. `ekit context` for the stack's `bdd.binding`, test layout and `agent_rules`.
   Read the feature's `features/*.feature`, `spec.md`, `plan.md` (contracts/data model).
   **Golden landing zone** (`ekit baseline status` shows one): read the reference slice first —
   `specs/000-reference-slice/features/greeting.feature`, `tests/acceptance/test_000_reference_slice.py`,
   `src/app/features/f000_reference/` — and the shared steps listed at the top of
   `tests/acceptance/conftest.py`. Copy their *shape*; never import the reference package, bind its
   feature file or reuse its ids (`RED-NO-EXEMPLAR`). The test module goes where
   `ekit context` / the golden seams say (`tests/acceptance/test_<NNN>_<slug>.py`).
   **Not golden** (`ekit baseline status` says `generate`): there is no reference slice and no feature package; do not look for `test_000_reference_slice.py` or `f000_reference`. Put the test module at `tests/acceptance/test_<NNN>_<slug>.py` and production stubs where `plan.md` says. If `tests/acceptance/conftest.py` has no fixture that creates the application and an HTTP test client (e.g. FastAPI `TestClient` around the app factory or `app` from the project's main module), add them there first: this is additive and allowed. Write the tests BEFORE running `ekit gate red`; a red run with no tests fails and tells you nothing.
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
   A `Given` step that simulates an outage/failure for a `Then` that checks error-handling behaviour must wire a
   real fault into the app under test (e.g. a FastAPI `app.dependency_overrides` override on the specific
   capability/dependency the scenario means to break, not the whole shared DB session, which would also break
   unrelated reads/writes earlier or later in the same scenario), not just record a flag with `ctx.remember(...)`.
   The gate surfaces an unwired fault step as a warning at red (`RED-STEPS-ASSERT`, `bdd.vacuous_steps`'s fault-step
   scan), before freeze, so fix it in the same commit rather than deferring it: once the file is frozen a fix needs
   `ekit unfreeze`.
   Each step function must be **self-contained**: never assume shared state (a dict key, a fixture value) was set
   by a step that belongs to a *different* scenario. In a golden landing zone every step takes
   `ctx: ScenarioContext` and uses `ctx.remember(...)` / `ctx.recall(...)`; a dict fixture or `scenario_state[...]`
   is rejected (`RED-STATE-TYPED`), and `ctx.recall` of a key this scenario never set fails as
   `MissingScenarioStateError`, which red rejects as broken glue (`RED-CLEAN-FAILURE`). Two scenarios that read almost the same, with one skipping a
   setup step the other has, are not interchangeable — the shorter one must set up what it needs itself. This is
   the single most common way a frozen test turns out to be broken rather than genuinely red.
3. Allowed production changes: only what makes the tests **compile and run** — empty routes or
   controllers returning 501, interfaces, DTO/record shells, DB migration stubs. No business
   logic, no happy-path behaviour. Golden landing zone: create the feature package printed by
   `ekit feature package <feature>` with route stubs whose body is `not_implemented()` (from
   `app.core.errors`), and register its router in `src/app/features/registry.py`. The core files are
   frozen; if a refused edit there seems necessary, stop and tell the user why.
4. Write unit tests for the domain rules named in `plan.md`, failing the same way.
5. Run `ekit gate red`. The gate runs the acceptance suite and requires that **every** scenario
   of this feature appears in the report and **fails**. If one passes, the test is not testing
   the new behaviour — fix the test. If one is missing or undefined, bind it.
   Failures must be assertion failures or 501/404 responses (404 only outside golden projects), not compile errors or crashes in
   the harness itself (the gate checks this too, `RED-CLEAN-FAILURE`: a `KeyError` or similar from
   broken test glue is rejected even though the scenario did technically fail).
   The gate also type-checks the feature's test module (`RED-GLUE-TYPED`): steps after the first failure never
   run in red, so every step must call real methods with the right types. In golden projects every scenario must
   fail with 501 from `not_implemented()`, never 404 (`RED-ROUTE-STUBBED`).
   If you were asked to come back and fix a specific frozen scenario after `ekit unfreeze` (rather
   than writing red for the first time), edit **only** the test file(s) named for that fix in this
   turn — no production code, no unrelated tasks, even ones still open on the task list. Mixing in
   other work here is exactly how a "fix the test" commit ends up not fixing the test.
6. If the gate report shows `RED-LINT` as a warning, fix the lint issue now, in the same commit as red: the
   feature's `.feature` and test files are not frozen yet at this point, so this is ordinary editing, not an
   unfreeze. Do not skip or wave off the warning, and do not defer it to green — green's own lint check
   (`GREEN-LINT`) will fail on it only after freeze, by which point fixing it needs `ekit unfreeze`.
7. When the gate passes, `ekit` freezes the feature files and bound tests against agent edits (`opencode.json`
   deny rules). Tell the user: restart OpenCode before the next step so the freeze is applied. A wrong test
   is lifted only by the user with `ekit unfreeze <feature> --reason "..."`.
8. Tell the user to commit now, before any implementation: the `.feature` files, the tests, `.ekit/ledger/`,
   `.ekit/freeze.yaml` and `opencode.json` (suggested message: `test(<NNN>): red for SCN-...`). The ledger is the
   evidence that tests came first, and `ekit gate red-recorded` / `green` fail (`REDREC-COMMITTED`) until the files
   recorded at red are committed exactly as recorded.
9. Hand off to `__SPECKIT_COMMAND_IMPLEMENT__`.
