---
description: Implement tasks only after red is recorded; finish only when gate green passes.
strategy: wrap
---

## Enterprise pre-flight

0. Active feature: run `ekit feature current --for implement "$ARGUMENTS"` and use exactly the folder
   name it prints. If it exits with an error, show the user its message (it lists the real features)
   and stop; do not choose a feature yourself.
1. Check that a red ledger entry exists for this feature: `ekit gate red-recorded`.
   **If there is none, STOP** and run `__SPECKIT_COMMAND_ESDLC_RED__` first. Never write
   production behaviour before the tests that prove it have been seen failing.
   If it fails only because the red evidence is not committed (`REDREC-COMMITTED`), STOP and ask the user to
   commit the feature files, tests and ledger first; do not commit or edit them yourself.
2. Run `ekit context` and follow the profile `agent_rules` and `controls` while coding.
3. Never edit `.feature` files, and never weaken assertions to get green.
   Split freeze (the default in golden projects: the feature's test module is not refused to your edit tool):
   when a step function itself is wrong, such as a method that does not exist, the wrong object, or the wrong
   return value, you MAY fix that step's BODY in the feature's own test module. Do not change step decorators,
   patterns, `target_fixture`, `scenarios()` calls or the assertions and expected values of `Then` steps; do not
   add skips, a new `conftest.py` or a new step module. `ekit gate green` checks this (`GREEN-CONTRACT-INTACT`,
   `GREEN-GLUE-NOT-WEAKENED`, `GREEN-NO-SHADOW-GLUE`) and re-runs the amended tests against the code as it was at
   red, where every scenario must still fail (`GREEN-GLUE-STILL-RED`). The diff is recorded for review.
   Strict freeze (the test module is refused to your edit tool): do not edit it; `GREEN-TESTS-UNCHANGED` fails on
   any change.
   If a scenario, a binding or an expected value is wrong, run
   `ekit blocked <feature> --reason "..." [--file PATH] [--scenario SCN-ID]` and stop: the fix goes through the
   spec (and possibly an open question), decided by a person.
4. Extend the landing zone, never rewrite it: do not delete or replace behaviour in baseline modules
   (`app/core`, health, app wiring) or their tests. Add new modules and wire them in.
   Golden landing zone: all code for this feature goes in its package (`ekit feature package <feature>`),
   its router is registered in `src/app/features/registry.py`, templates in
   `src/app/templates/features/<slug>/`, migrations in `migrations/versions/`. The core and the shared
   test helpers are frozen (`GREEN-GOLDEN-INTACT` fails on any change to them).
5. If an edit is refused by a permission rule (frozen tests, ekit files), stop and report it. Never route around it
   with shell commands.
6. Work in slices of two or three scenarios; run `ekit run acceptance` after each slice.
7. **Change requests** (`ekit change show --feature <feature>` prints one): change only what the request
   needs, in the package(s) `ekit feature package <feature>` prints (golden), and keep every existing
   scenario green: `ekit gate green` runs the whole acceptance suite, so a regression in another feature
   fails it. If `GREEN-CHANGE-SUPERSEDED` fails, an old scenario still asserts the behaviour this change
   replaces: stop and tell the user the `ekit change retire …` command it prints (a person runs it).

{CORE_TEMPLATE}

## Enterprise post-flight

4. Run `ekit gate green`. Fix code (not tests) until it passes. If a check cannot pass for a
   legitimate reason, explain it to the user; do not edit the policy.
5. Tick the remaining tasks in `tasks.md`, commit code together with the `.ekit/ledger/` entry,
   and report: scenarios green, coverage, any warnings (e.g. SCA).
