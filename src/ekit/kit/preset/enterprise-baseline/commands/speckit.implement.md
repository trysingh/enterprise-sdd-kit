---
description: Implement tasks only after red is recorded; finish only when gate green passes.
strategy: wrap
---

## Enterprise pre-flight

0. Active feature: use the feature named in `$ARGUMENTS` (`001-user-admin`, `001`). If none is named,
   run `ekit status` and take the one feature whose `red` column is `ok` and `green` is `--`; if several
   qualify, ask once which. Do not guess.
1. Check that a red ledger entry exists for this feature: `ekit gate red-recorded`.
   **If there is none, STOP** and run `__SPECKIT_COMMAND_ESDLC_RED__` first. Never write
   production behaviour before the tests that prove it have been seen failing.
   If it fails only because the red evidence is not committed (`REDREC-COMMITTED`), STOP and ask the user to
   commit the feature files, tests and ledger first; do not commit or edit them yourself.
2. Run `ekit context` and follow the profile `agent_rules` and `controls` while coding.
3. Do not edit `.feature` files or the acceptance tests recorded at red, and do not weaken assertions to get green.
   `ekit gate green` fails on any change (`GREEN-TESTS-UNCHANGED`). If a scenario or test is wrong,
   stop and say so; the fix goes through the spec (and possibly an open question).
4. Extend the landing zone, never rewrite it: do not delete or replace behaviour in baseline modules
   (`app/core`, health, app wiring) or their tests. Add new modules and wire them in.
5. If an edit is refused by a permission rule (frozen tests, ekit files), stop and report it. Never route around it
   with shell commands.
6. Work in slices of two or three scenarios; run `ekit run acceptance` after each slice.

{CORE_TEMPLATE}

## Enterprise post-flight

4. Run `ekit gate green`. Fix code (not tests) until it passes. If a check cannot pass for a
   legitimate reason, explain it to the user; do not edit the policy.
5. Tick the remaining tasks in `tasks.md`, commit code together with the `.ekit/ledger/` entry,
   and report: scenarios green, coverage, any warnings (e.g. SCA).
